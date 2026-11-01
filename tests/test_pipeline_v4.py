import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from marketplace_agent.core import ValidationError
from marketplace_agent.pipeline import daily_counts, feedback_state, materialize, plan, record_feedback, run, settings, upload_gate

NOW=datetime(2026,11,1,18,tzinfo=timezone.utc)


class PipelineV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.policy=json.loads((ROOT/'config/pipeline.v4.example.json').read_text(encoding='utf8'))
        self.item=json.loads((ROOT/'data/catalog.v4.sample.json').read_text(encoding='utf8'))[0]
        self.item['price_confirmed_at']=NOW.isoformat()
        for n in range(5):
            path=self.root/f'fixture-{n}.webp'
            # Fictitious bytes test integrity, not image decoding.
            path.write_bytes(f'FICTIONAL IMAGE FIXTURE {n}'.encode())
            self.item['photos'].append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                product_source_url=self.item['source_url'],ownership_evidence='FICTIONAL',visual_review_confirmed=True))

    def event(self,result='REJECTED_DUPLICATE',platform='FACEBOOK',**extra):
        return dict(event_id='DEMO-EVENT-001',product_id=self.item['id'],platform=platform,
                    result=result,live_confirmed=result=='LIVE',evidence='FICTIONAL',**extra)

    def run_plan(self,history=None,item=None):
        return plan([item or self.item],self.policy,history or [],at=NOW)

    def test_submitted_and_rejected_never_count_as_live(self):
        for result in ('UNKNOWN','REJECTED_DUPLICATE','REJECTED_OTHER'):
            event=self.event(result,submitted_at=NOW.isoformat());event['live_confirmed']=True
            self.assertNotEqual(feedback_state(event),'LIVE')
            self.assertEqual(daily_counts([event],self.policy,at=NOW)['TOTAL'],0)

    def test_duplicate_quarantine_replacement_and_independent_platforms(self):
        for platform in ('FACEBOOK','OLX'):
            result=self.run_plan([self.event(platform=platform)])
            self.assertEqual(result[platform]['quarantine'],[self.item['id']])
            self.assertEqual(result[platform]['replacement_required'],1)
            self.assertEqual(result[platform]['ready'],[])
            other='OLX' if platform=='FACEBOOK' else 'FACEBOOK'
            self.assertEqual(len(result[other]['ready']),1)

    def test_platform_photo_thresholds_ownership_and_unique_hashes(self):
        self.item['photos']=self.item['photos'][:1]
        self.assertEqual(len(self.run_plan()['OLX']['ready']),1)
        self.assertEqual(self.run_plan()['OLX']['photo_quality']['MINIMAL'],1)
        self.assertEqual(self.run_plan()['FACEBOOK']['ready'],[])
        self.item['photos']*=5
        self.assertEqual(self.run_plan()['FACEBOOK']['ready'],[])
        self.item['photos'][0]['ownership_evidence']=None
        self.assertEqual(self.run_plan()['OLX']['ready'],[])

    def test_changed_photos_fail_preflight(self):
        for photo in self.item['photos']:Path(photo['path']).write_bytes(b'CHANGED')
        self.assertEqual(self.run_plan()['OLX']['ready'],[])

    def test_live_does_not_repeat_on_either_target(self):
        for platform in ('FACEBOOK','OLX'):
            result=self.run_plan([self.event('LIVE',platform)])
            self.assertEqual(result[platform]['ready'],[])
            other='OLX' if platform=='FACEBOOK' else 'FACEBOOK'
            self.assertEqual(len(result[other]['ready']),1)

    def test_pending_submission_does_not_requeue(self):
        self.assertEqual(self.run_plan([self.event('UNKNOWN','OLX')])['OLX']['ready'],[])

    def test_unconfirmed_missing_and_stale_price_evidence(self):
        for field,value in (('price_confirmed',False),('price_confirmed_at',None),('price_confirmed_at','2020-01-01T00:00:00Z')):
            item=copy.deepcopy(self.item);item[field]=value
            self.assertEqual(self.run_plan(item=item)['OLX']['ready'],[])

    def test_source_aliases_cannot_repeat_or_inflate_daily_counts(self):
        other=copy.deepcopy(self.item);other['id']='DEMO-V4-002'
        self.assertEqual(plan([self.item,other],self.policy,[],at=NOW)['OLX']['ready'],[])
        event=self.event('LIVE','OLX',source_url=self.item['source_url'],submitted_at=NOW.isoformat());event['product_id']='OLD-ID'
        self.assertEqual(self.run_plan([event])['OLX']['ready'],[])
        alias={**event,'product_id':'ANOTHER-ID'}
        self.assertEqual(daily_counts([event,alias],self.policy,at=NOW)['OLX'],1)

    def test_fifteen_main_and_five_preflighted_diverse_reserves(self):
        items=[]
        for n in range(20):
            item=copy.deepcopy(self.item);item['id']=f'DEMO-{n:02}';item['category']=f'Category-{n%4}'
            item['source_url']=f'https://example.com/catalog/demo-{n:02}'
            for photo in item['photos']:photo['product_source_url']=item['source_url']
            items.append(item)
        result=plan(items,self.policy,[],at=NOW)
        self.assertEqual(len(result['FACEBOOK']['ready']),15)
        self.assertEqual(len(result['FACEBOOK']['reserves']),5)
        self.assertEqual(len({x['category'] for x in result['FACEBOOK']['ready'][:4]}),4)

    def test_inventory_cep_moderation_and_mode_gates(self):
        item=self.run_plan()['FACEBOOK']['ready'][0]
        inv=dict(platform='OLX',authenticated=True,complete=True,checked_at=NOW.isoformat(),listings=[])
        self.assertIn('OLX_CEP_REQUIRED',upload_gate(item,'OLX',self.policy,[],inv,at=NOW))
        self.assertIn('SELLER_INVENTORY_NOT_VERIFIED',upload_gate(item,'FACEBOOK',self.policy,[],inv,at=NOW))
        inv.update(blocking_issue='PLATFORM_MODERATION',checked_at='2020-01-01T00:00:00Z',listings=[{'product_id':item['id']}])
        errors=upload_gate(item,'OLX',self.policy,[],inv,at=NOW)
        for code in ('HUMAN_ACTION_REQUIRED','SELLER_INVENTORY_STALE','EXISTING_LISTING_REVIEW_REQUIRED'):self.assertIn(code,errors)
        for mode,code in (('PREPARE_ONLY','PREPARE_ONLY'),('AUTO_POST_WHERE_SUPPORTED','SUPPORTED_ADAPTER_REQUIRED')):
            self.policy['olx_mode']=mode
            self.assertIn(code,upload_gate(item,'OLX',self.policy,[],inv,at=NOW))

    def test_feedback_confirmation_idempotency_collision_and_rollback(self):
        event=self.event()
        with self.assertRaises(ValidationError):record_feedback(self.root,event)
        record_feedback(self.root,event,confirmed=True);record_feedback(self.root,event,confirmed=True)
        path=self.root/'v4/platform-feedback.json';before=path.read_bytes()
        with self.assertRaises(ValidationError):record_feedback(self.root,{**event,'price':'changed'},confirmed=True)
        with patch('marketplace_agent.pipeline.atomic_json',side_effect=OSError('FICTIONAL DISK FAILURE')):
            with self.assertRaises(OSError):record_feedback(self.root,{**event,'event_id':'DEMO-EVENT-002'},confirmed=True)
        self.assertEqual(before,path.read_bytes())
        self.assertFalse((self.root/'v4/.feedback.lock').exists())

    def test_live_needs_evidence_and_aware_timestamps(self):
        event=self.event('LIVE');event['evidence']=None
        with self.assertRaises(ValidationError):record_feedback(self.root,event,confirmed=True)
        with self.assertRaises(ValidationError):record_feedback(self.root,self.event('LIVE',submitted_at='2026-11-01T12:00:00'),confirmed=True)

    def test_daily_counts_use_local_day_and_distinct_platform_products(self):
        events=[self.event('LIVE',p,submitted_at='2026-11-02T01:00:00Z') for p in ('FACEBOOK','OLX')]
        events.append(dict(events[0]))
        self.assertEqual(daily_counts(events,self.policy,at=NOW),{'FACEBOOK':1,'OLX':1,'TOTAL':2})

    def test_materialization_omission_integrity_and_failed_batch_pointer(self):
        result=self.run_plan();folder=Path(materialize(self.root,result,self.policy))
        for platform in ('FACEBOOK','OLX'):
            base=folder/platform/self.item['id'];text=(base/'anuncio.txt').read_text(encoding='utf8')
            for omitted in ('Atributo conflitante','Trecho incompleto','Consulte condições'):self.assertNotIn(omitted,text)
            self.assertEqual(len(list((base/'imagens').iterdir())),5)
            payload=json.loads((base/'payload.json').read_text(encoding='utf8'))
            self.assertEqual(payload['status'],'READY_TO_POST')
            self.assertFalse(payload['live_confirmed'])
            if platform=='OLX':self.assertIsNone(payload['operation_location']['cep'])
            self.assertTrue((folder/platform/'TODOS_OS_POSTS.txt').is_file())
        self.assertTrue((folder/'FACEBOOK'/self.item['id']/'identificacoes.txt').is_file())
        pointer=(self.root/'v4/current-batch.json').read_bytes()
        with patch('marketplace_agent.pipeline.shutil.copy2',side_effect=OSError('FICTIONAL DISK FAILURE')):
            with self.assertRaises(OSError):materialize(self.root,result,self.policy)
        self.assertEqual(pointer,(self.root/'v4/current-batch.json').read_bytes())

    def test_tire_source_lifecycle_states_and_config_policy(self):
        self.assertEqual(self.run_plan()['TIRE_BLOCKER'],'TIRE_CATALOG_SOURCE_MISSING')
        self.item['kind']='TIRE';self.assertEqual(self.run_plan()['OLX']['ready'],[]);self.item.pop('kind')
        for state in ('SOLD','ARCHIVED','NEEDS_REVIEW'):
            self.item['platform_status']={'OLX':state};self.assertEqual(self.run_plan()['OLX']['ready'],[])
        for field,value in (('olx_mode','UNSUPPORTED'),('auto_retry',True),('safe_omission',False)):
            with self.assertRaises(ValidationError):settings({**self.policy,field:value})

    def test_cli_plan_is_fictional_and_does_not_claim_ready_or_live(self):
        result=subprocess.run([sys.executable,'scripts/marketplace.py','--workspace',str(self.root),'v4','plan'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        output=json.loads(result.stdout)
        self.assertEqual(output['EVIDENCE_MODE'],'FICTIONAL')
        self.assertEqual(output['OLX']['ready'],[])
        self.assertEqual(output['LIVE_TODAY']['TOTAL'],0)

    def test_legacy_publication_blocks_without_inventing_current_live(self):
        from marketplace_agent.core import config
        from marketplace_agent.storage import Store
        from marketplace_agent.workflow import MarketplaceAgent
        agent=MarketplaceAgent(Store(self.root),config(json.loads((ROOT/'config/config.example.json').read_text())))
        agent.prepare([self.item])
        agent.record('publication',self.item['id'],event_id='LEGACY-DEMO-PUBLICATION',confirmed=True,listing_url='https://example.com/listing/demo')
        result=run(self.root,self.policy,[self.item],'plan')
        self.assertIn('TARGET_STATE_REQUIRES_REVIEW',result['FACEBOOK']['blockers'][self.item['id']])
        self.assertEqual(result['LIVE_TODAY']['TOTAL'],0)

    def test_daily_target_stops_further_uploads(self):
        events=[]
        for n in range(15):
            event=self.event('LIVE','OLX',submitted_at=NOW.isoformat())
            event['product_id']=f'OTHER-{n}'
            events.append(event)
        item=self.run_plan()['OLX']['ready'][0]
        self.assertIn('DAILY_TARGET_REACHED',upload_gate(item,'OLX',self.policy,events,None,at=NOW))


if __name__=='__main__':unittest.main()
