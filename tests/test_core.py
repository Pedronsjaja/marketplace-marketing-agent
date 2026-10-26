import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from marketplace_agent.core import State, ValidationError, config, product, transition
from marketplace_agent.storage import Store, atomic_json, read_control, write_control
from marketplace_agent.workflow import MarketplaceAgent
from marketplace_agent.routing import route, validate_benchmark
from marketplace_agent.manager import metrics, analyze

POLICY = json.loads((ROOT/"config/config.example.json").read_text())
PRODUCTS = json.loads((ROOT/"data/catalog.sample.json").read_text())


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root/"workspace")
        self.agent = MarketplaceAgent(self.store, POLICY)
        self.item = dict(PRODUCTS[0])

    def prepare(self):
        return self.agent.prepare([self.item])

    def published(self):
        self.prepare()
        self.agent.record("publication", self.item["id"], event_id="publish-1", confirmed=True,
                          listing_url="https://example.invalid/listing/demo-1")

    def record(self, kind, event_id, **kw):
        return self.agent.record(kind, self.item["id"], event_id=event_id, confirmed=True, **kw)

    def test_prepare_is_cached_and_unchanged(self):
        self.assertEqual(self.prepare()["results"][0]["result"], "PREPARED")
        before = self.store.path.read_bytes()
        self.assertEqual(self.prepare()["results"][0]["result"], "CACHE_HIT")
        self.assertEqual(before, self.store.path.read_bytes())

    def test_secondary_conflict_does_not_block_valid_preparation(self):
        result = self.agent.prepare([self.item], ["public_contact"])
        self.assertEqual(result["results"][0]["result"], "PREPARED")
        self.assertIn("persistent policy preserved", result["adjustments"][0])
        self.assertFalse(self.agent.policy["allow_public_contact"])

    def test_bad_product_does_not_block_valid_product(self):
        bad = {**PRODUCTS[1], "price": "-1"}
        result = self.agent.prepare([bad, self.item])
        self.assertEqual([r["result"] for r in result["results"]], ["ERROR", "PREPARED"])

    def test_catalog_duplicates_skipped_without_first_wins(self):
        result = self.agent.prepare([self.item, self.item, PRODUCTS[1]])
        self.assertEqual([r["result"] for r in result["results"]], ["ERROR", "ERROR", "PREPARED"])

    def test_changed_input_invalidates_unpublished_cache(self):
        self.prepare()
        self.item["price"] = "45.00"
        self.assertEqual(self.prepare()["results"][0]["result"], "PREPARED")
        self.assertIn("45.00", self.store.snapshot()["records"][self.item["id"]]["draft"])

    def test_published_product_is_immutable_to_prepare(self):
        self.published()
        before = self.store.path.read_bytes()
        self.item["price"] = "100.00"
        self.assertEqual(self.prepare()["results"][0]["result"], "PRESERVED_PUBLISHED")
        self.assertEqual(before, self.store.path.read_bytes())

    def test_confirmation_required(self):
        self.prepare()
        with self.assertRaises(ValidationError):
            self.agent.record("publication", self.item["id"], event_id="publish-1", listing_url="https://example.invalid/p")
        self.assertEqual(self.store.snapshot()["records"][self.item["id"]]["state"], "PRONTO_PARA_PUBLICAR")

    def test_duplicate_event_id_is_retry_safe(self):
        self.published()
        self.record("leads", "lead-1", leads=2)
        result = self.record("leads", "lead-1", leads=2)
        self.assertEqual(result["result"], "DUPLICATE_IGNORED")
        self.assertEqual(self.store.snapshot()["records"][self.item["id"]]["leads"], 2)
        with self.assertRaises(ValidationError):
            self.record("leads", "lead-1", leads=3)

    def test_failed_event_rolls_back(self):
        self.published()
        self.record("leads", "lead-1", leads=1)
        before = self.store.path.read_bytes()
        with self.assertRaises(ValidationError):
            self.record("forwarding", "forward-1", forwarded=2)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertFalse((self.store.root/".writer.lock").exists())

    def test_incremental_lost_then_sale(self):
        self.published()
        self.record("leads", "lead-1", leads=2)
        self.record("forwarding", "forward-1", forwarded=2)
        self.record("outcome", "outcome-1", lost=1)
        self.record("outcome", "outcome-2", sales=1)
        row=self.store.snapshot()["records"][self.item["id"]]
        self.assertEqual((row["state"], row["sales"], row["lost"]), ("VENDA",1,1))

    def test_incremental_sale_then_lost(self):
        self.published()
        self.record("leads", "lead-1", leads=2)
        self.record("forwarding", "forward-1", forwarded=2)
        self.record("outcome", "outcome-1", sales=1)
        self.record("outcome", "outcome-2", lost=1)
        self.assertEqual(self.store.snapshot()["records"][self.item["id"]]["sales"], 1)

    def test_forward_remaining_lead_after_outcome(self):
        self.published()
        self.record("leads", "lead-1", leads=2)
        self.record("forwarding", "forward-1", forwarded=1)
        self.record("outcome", "outcome-1", lost=1)
        self.record("forwarding", "forward-2", forwarded=1)
        self.record("outcome", "outcome-2", sales=1)
        self.assertEqual(self.store.snapshot()["records"][self.item["id"]]["forwarded"], 2)

    def test_new_leads_during_existing_outcomes(self):
        self.published()
        self.record("leads", "lead-1", leads=1)
        self.record("forwarding", "forward-1", forwarded=1)
        self.record("leads", "lead-2", leads=1)
        self.record("outcome", "outcome-1", sales=1)
        row = self.store.snapshot()["records"][self.item["id"]]
        self.assertEqual((row["leads"], row["sales"]), (2, 1))

    def test_duplicate_listing_url_blocked(self):
        self.published()
        self.agent.prepare([PRODUCTS[1]])
        with self.assertRaises(ValidationError):
            self.agent.record("publication", PRODUCTS[1]["id"], event_id="publish-2", confirmed=True,
                              listing_url="https://example.invalid/listing/demo-1")

    def test_state_root_and_event_validation(self):
        for bad in ([], {"schema_version":1,"records":{},"events":[3]}):
            atomic_json(self.store.path,bad)
            with self.assertRaises(ValidationError):
                self.store.snapshot()

    def test_lock_prevents_concurrent_writer(self):
        self.prepare()
        lock=self.store.root/".writer.lock"
        lock.write_text("")
        self.assertEqual(self.prepare()["results"][0]["result"], "ERROR")
        self.assertTrue(lock.exists())

    def test_atomic_replace_failure_preserves_prior_state(self):
        self.prepare()
        before=self.store.path.read_bytes()
        with patch("marketplace_agent.storage.os.replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                atomic_json(self.store.path, {"replacement":True})
        self.assertEqual(before,self.store.path.read_bytes())

    def test_csv_roundtrip_and_exclusive_export(self):
        self.published()
        rows=list(self.store.snapshot()["records"].values())
        path=self.root/"export.csv"
        write_control(path, rows)
        result=read_control(path)
        self.assertEqual(result[0]["product_id"],self.item["id"])
        with self.assertRaises(FileExistsError):
            write_control(path, rows)

    def test_cli_missing_confirmation_and_no_traceback(self):
        p=subprocess.run([sys.executable, str(ROOT/"scripts/marketplace.py"),
                          "--workspace",str(self.store.root),"record-leads","DEMO-001",
                          "--event-id","lead-1","--count","1"],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        self.assertNotIn("Traceback",p.stderr)

    def test_cli_partial_failure_exit_one(self):
        catalog=self.root/"catalog.json"
        atomic_json(catalog,[{**self.item,"price":"NaN"},PRODUCTS[1]])
        p=subprocess.run([sys.executable,str(ROOT/"scripts/marketplace.py"),
                          "--workspace",str(self.store.root),"prepare","--catalog",str(catalog)],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,1)
        self.assertIn("DEMO-002",self.store.snapshot()["records"])


class DomainTests(unittest.TestCase):
    def test_illegal_state_jump(self):
        with self.assertRaises(ValidationError):
            transition(State.IDENTIFICADO,State.VENDA,confirmed=True)

    def test_config_rejects_string_boolean_and_unknown_field(self):
        for bad in ({**POLICY,"allow_groups":"false"},{**POLICY,"unknown":True}):
            with self.assertRaises(ValidationError):config(bad)

    def test_invalid_prices_and_evidence(self):
        for value in ("NaN","Infinity","-1","0","1.001",True,3.0):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):product({**PRODUCTS[0],"price":value})
        with self.assertRaises(ValidationError):product({**PRODUCTS[0],"verified":False})

    def test_credentials_in_url_rejected(self):
        with self.assertRaises(ValidationError):
            product({**PRODUCTS[0],"source_url":"https://user:pass@example.invalid/p"})

    def test_metrics_match_checked_in_sample(self):
        result=metrics(read_control(ROOT/"data/control.sample.csv"))
        with (ROOT/"data/metrics.sample.csv").open(newline="") as stream:
            for row in csv.DictReader(stream):
                self.assertAlmostEqual(result[row["metric"]],float(row["value"]))
        self.assertEqual(result["leads"],12)

    def test_empty_denominator_is_unknown(self):
        self.assertIsNone(metrics([])["sales_per_lead"])

    def test_manager_labels_and_priority(self):
        result=analyze(read_control(ROOT/"data/control.sample.csv"))
        self.assertTrue({"FATO","HIPOTESE","RECOMENDACAO"}.issubset(result))
        self.assertEqual(result["priority"][0],"DEMO-002")

    def test_inconsistent_metrics_rejected(self):
        with self.assertRaises(ValidationError):
            metrics([dict(product_id="DEMO",state="VENDA",leads=1,forwarded=1,sales=1,lost=1)])

    def test_csv_duplicate_and_width(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"x.csv"
            header="product_id,state,leads,forwarded,sales,lost\n"
            for rows in ("A,PUBLICADO,0,0,0,0\nA,PUBLICADO,0,0,0,0\n","A,PUBLICADO,0,0,0,0,extra\n"):
                p.write_text(header+rows)
                with self.assertRaises(ValidationError):read_control(p)


class RoutingTests(unittest.TestCase):
    def test_deterministic_first(self):
        self.assertEqual(route("metrics",{},available_levels=[1,2,3],allow_cloud=True,allow_premium=True).level,0)

    def test_local_before_cloud(self):
        self.assertEqual(route("copy",{},available_levels=[1,2,3],allow_cloud=True,allow_premium=True).level,1)

    def test_cloud_requires_permission(self):
        self.assertIsNone(route("copy",{},available_levels=[2,3]).level)

    def test_premium_requires_separate_permission(self):
        self.assertIsNone(route("copy",{},available_levels=[3],allow_cloud=True).level)

    def test_explicit_failed_level_escalates(self):
        self.assertEqual(route("copy",{},available_levels=[1,2,3],failed_levels=[1],allow_cloud=True).level,2)

    def test_cache_key_tracks_prompt_and_payload(self):
        base=route("copy",{"product":"A"}).cache_key
        self.assertNotEqual(base,route("copy",{"product":"B"}).cache_key)
        self.assertNotEqual(base,route("copy",{"product":"A"},prompt_version="2").cache_key)

    def test_invalid_task_and_level(self):
        for kwargs in ({"task":"unknown"},{"task":"copy","available_levels":[0]}):
            with self.assertRaises(ValidationError):route(payload={},**kwargs)

    def test_benchmark_unknowns_are_accepted(self):
        record=json.loads((ROOT/"benchmarks/result.example.json").read_text())
        validate_benchmark(record)
        self.assertIsNone(record["input_tokens"])

if __name__=="__main__":
    unittest.main()
