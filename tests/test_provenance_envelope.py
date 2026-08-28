#!/usr/bin/env python3
import importlib.util, unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'src/system/provenance-envelope.py'
spec=importlib.util.spec_from_file_location('pe',P); pe=importlib.util.module_from_spec(spec); spec.loader.exec_module(pe)
class T(unittest.TestCase):
 def test_external_is_data_only_and_hash_bound(self):
  e=pe.envelope({'server_id':'xyz'},source='mcp',origin='server-a',timestamp=1)
  self.assertEqual(e['authority'],'data_only'); self.assertEqual(pe.validate(e),[])
  e['content']['server_id']='tampered'; self.assertIn('content hash mismatch',pe.validate(e))
 def test_external_cannot_self_promote(self):
  with self.assertRaises(ValueError): pe.envelope({},source='web',origin='example.com',trust_class='internal_trusted')
 def test_detects_nested_authority_claims(self):
  self.assertEqual(pe.authority_claims({'result':{'runtime_config':{'shell':True}}}),['$.result.runtime_config'])
if __name__=='__main__': unittest.main(verbosity=2)
