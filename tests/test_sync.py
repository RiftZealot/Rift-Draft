import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

P=Path(__file__).resolve().parents[1]/'scripts'/'sync_data.py'
spec=importlib.util.spec_from_file_location('sync_data',P)
sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)


def fixture(role,patch,kind):
    data={'schema_version':2,'lane':role,'matchups':{str(i):{} for i in range(50,110)},
          'tierlist':{'122':{'games':2000,'wr':50.1,'pr':2.1}}}
    if kind=='recent':data.update(patch=patch,scraped_at='2026-11-13T00:00:00Z')
    else:data.update(source_patches=[patch]+['16.'+str(i) for i in range(21,2,-1)],generated_at='2026-11-13T00:00:00Z')
    return data

class TestUpdater(unittest.TestCase):
    def test_current_patch_all_roles(self):
        def get(url):
            if url==sync.VERSIONS:return ['16.22.1','16.21.1']
            if url==sync.API:return [{'name':x,'type':'dir'} for x in ['16.21','16.22','16.23']]
            role=url.rsplit('/',1)[-1].removesuffix('.json')
            return fixture(role,'16.22','history' if '/weighted/' in url else 'recent')
        with TemporaryDirectory() as tmp:
            m=sync.build(Path(tmp),get)
            self.assertEqual(m['source_patch'],'16.22')
            self.assertTrue(m['source_fresh'])
            self.assertEqual(sum(v['available'] for d in ['recent','history'] for v in m[d].values()),10)
            self.assertTrue((Path(tmp)/'data/recent/support.json').exists())

    def test_lag_never_claimed_current(self):
        def get(url):
            if url==sync.VERSIONS:return ['16.23.1','16.22.1']
            if url==sync.API:return [{'name':'16.22','type':'dir'}]
            role=url.rsplit('/',1)[-1].removesuffix('.json')
            return fixture(role,'16.22','history' if '/weighted/' in url else 'recent')
        with TemporaryDirectory() as tmp:
            m=sync.build(Path(tmp),get)
            self.assertEqual(m['riot_patch'],'16.23')
            self.assertEqual(m['source_patch'],'16.22')
            self.assertFalse(m['source_fresh'])

    def test_bad_patch_rejected_without_wrong_patch_data(self):
        def get(url):
            if url==sync.VERSIONS:return ['16.22.1']
            if url==sync.API:return [{'name':'16.22','type':'dir'}]
            role=url.rsplit('/',1)[-1].removesuffix('.json')
            return fixture(role,'16.21' if role=='support' else '16.22','history' if '/weighted/' in url else 'recent')
        with TemporaryDirectory() as tmp:
            m=sync.build(Path(tmp),get)
            self.assertFalse(m['recent']['support']['available'])
            self.assertFalse(m['history']['support']['available'])
            self.assertFalse((Path(tmp)/'data/recent/support.json').exists())

    def test_valid_old_copy_retained_if_download_unavailable(self):
        def get(url):
            if url==sync.VERSIONS:return ['16.22.1']
            if url==sync.API:return [{'name':'16.22','type':'dir'}]
            role=url.rsplit('/',1)[-1].removesuffix('.json')
            if role=='jungle' and '/weighted/' in url:raise RuntimeError('temporary outage')
            return fixture(role,'16.22','history' if '/weighted/' in url else 'recent')
        with TemporaryDirectory() as tmp:
            p=Path(tmp)
            sync.atomic_json(p/'data/history/jungle.json',fixture('jungle','16.22','history'))
            m=sync.build(p,get)
            self.assertTrue(m['history']['jungle']['retained_from_previous_build'])

if __name__=='__main__':unittest.main()
