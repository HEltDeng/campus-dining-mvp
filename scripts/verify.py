"""Run isolated temporary-database tests and retain a concise verification report."""
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
stream=io.StringIO()
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
output=stream.getvalue()
print(output)
node=subprocess.run(['node','--check',str(ROOT/'web/app.js')],capture_output=True,text=True)
report={'date':'2026-10-13 Asia/Singapore','status':'PASS' if result.wasSuccessful() and node.returncode==0 else 'FAIL','isolated_database_tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'javascript_syntax':'PASS' if node.returncode==0 else 'FAIL','database_scope':'Each test uses a fresh TemporaryDirectory SQLite database; the running demo database is untouched.','real_transactions':'NOT_EXECUTED','log':output}
folder=ROOT/'docs/evidence';folder.mkdir(parents=True,exist_ok=True)
(folder/'automated-tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
sys.exit(0 if report['status']=='PASS' else 1)
