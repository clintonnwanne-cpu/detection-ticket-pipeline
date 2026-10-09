import unittest
from pipeline import connect, process
E={'event_id':'e1','finding_id':'f1','asset_id':'a1','observed_at':'2026-10-08T12:00:00Z','status':'open'}
class PipelineTests(unittest.TestCase):
 def setUp(self): self.db=connect(':memory:'); self.owners={'a1':'demo-team'}
 def tearDown(self): self.db.close()
 def send(self,e=E,fail=False): return process(self.db,e,self.owners,fail)
 def count(self,table): return self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]
 def test_create(self): self.assertEqual(self.send(),'created')
 def test_duplicate(self):
  self.send(); self.assertEqual(self.send(),'duplicate'); self.assertEqual(self.count('tickets'),1)
 def test_collision(self):
  self.send(); self.assertEqual(self.send({**E,'status':'resolved'}),'id_collision'); self.assertEqual(self.count('dead_letters'),1)
 def test_retry(self):
  self.assertEqual(self.send(fail=True),'retry'); self.assertEqual(self.count('tickets'),0); self.assertEqual(self.count('events'),0); self.assertEqual(self.send(),'created')
 def test_out_of_order(self):
  self.send(); self.assertEqual(self.send({**E,'event_id':'e0','observed_at':'2026-10-07T12:00:00Z'}),'out_of_order')
 def test_newer(self):
  self.send(); self.assertEqual(self.send({**E,'event_id':'e2','observed_at':'2026-10-09T12:00:00Z','status':'resolved'}),'updated'); self.assertEqual(self.count('tickets'),1)
 def test_same_time(self):
  self.send(); self.assertEqual(self.send({**E,'event_id':'e2','status':'resolved'}),'same_time_conflict')
 def test_missing_owner_replay(self):
  self.owners={}; self.assertEqual(self.send(),'dead_letter'); self.owners={'a1':'demo-team'}; self.assertEqual(self.send(),'created')
 def test_malformed(self): self.assertEqual(self.send({'event_id':'broken'}),'dead_letter')
 def test_naive_time(self): self.assertEqual(self.send({**E,'observed_at':'2026-10-08T12:00:00'}),'dead_letter')
 def test_non_object(self): self.assertEqual(self.send([]),'dead_letter')
 def test_audit(self): self.send(); self.send(); self.assertEqual(self.count('audit'),2)
if __name__=='__main__': unittest.main()
