#!/usr/bin/env python3
"""Build same-origin Rift Draft matchup data for GitHub Pages.

No API key or external Python dependencies required. This updater selects the
newest dataset patch that does not exceed the live Riot/Data Dragon patch and
publishes a manifest that makes source lag and missing files explicit.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROLES = ('top','jungle','middle','bottom','support')
REPO = 'shizukaziye/lol-pool-coverage'
RAW = 'https://raw.githubusercontent.com/'+REPO+'/main/data'
API = 'https://api.github.com/repos/'+REPO+'/contents/data/snapshots'
VERSIONS = 'https://ddragon.leagueoflegends.com/api/versions.json'
PATCH_RE = re.compile(r'^\d{2}\.\d{1,2}$')
USER_AGENT='RiftDraft-Pages-Updater/1.0 (public data mirror; github actions)'


def fetch_json(url: str, retries=3):
    err = None
    for attempt in range(retries):
        try:
            headers={'User-Agent': USER_AGENT, 'Accept':'application/json'}
            if url.startswith('https://api.github.com/') and os.getenv('GITHUB_TOKEN'):
                headers['Authorization']='Bearer '+os.environ['GITHUB_TOKEN']
            req=Request(url, headers=headers)
            with urlopen(req, timeout=45) as res:
                raw = res.read(45_000_001)
                if len(raw) > 45_000_000:
                    raise ValueError('JSON response exceeds max file size')
            return json.loads(raw)
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
            err = e
            if attempt+1 < retries: time.sleep(1+attempt*2)
    raise RuntimeError(f'Could not retrieve {url}: {err}')


def patch_key(s):
    if not PATCH_RE.fullmatch(str(s)): raise ValueError('Invalid patch: '+str(s))
    a, b = map(int, str(s).split('.'))
    return a,b


def current_patch(versions):
    if not isinstance(versions, list): raise ValueError('Unexpected Riot Data Dragon version list')
    for v in versions:
        if isinstance(v, str):
            p='.'.join(v.split('.')[:2])
            if PATCH_RE.fullmatch(p): return p, v
    raise ValueError('Riot version list does not contain recognizable patches')


def newest_supported_patch(folders, live):
    live_key=patch_key(live)
    options=[item['name'] for item in folders if isinstance(item,dict) and
             item.get('type')=='dir' and PATCH_RE.fullmatch(str(item.get('name',''))) and
             patch_key(item['name']) <= live_key]
    if not options: raise ValueError('No available upstream patch at or below live Riot patch '+live)
    return max(options, key=patch_key)


def validate(obj, role, expected_patch, kind):
    if not isinstance(obj,dict) or obj.get('lane')!=role or obj.get('schema_version')!=2:
        return False
    if not isinstance(obj.get('tierlist'),dict) or not isinstance(obj.get('matchups'),dict):
        return False
    if len(obj['matchups'])<50:return False
    if kind=='recent':
        return obj.get('patch')==expected_patch and isinstance(obj.get('scraped_at'),str)
    patches=obj.get('source_patches')
    return (isinstance(patches,list) and len(patches)==20 and
            patches[0]==expected_patch and isinstance(obj.get('generated_at'),str))


def atomic_json(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    out=json.dumps(obj,separators=(',',':'),ensure_ascii=False)
    staged=path.with_suffix(path.suffix+'.tmp')
    staged.write_text(out,encoding='utf-8')
    staged.replace(path)
    return sha256(out.encode('utf-8')).hexdigest()


def build(site: Path, fetcher=fetch_json):
    try:
        live, version=current_patch(fetcher(VERSIONS))
    except Exception as exc:
        raise RuntimeError('Refusing to claim a live patch without Riot version verification: '+str(exc))
    source=newest_supported_patch(fetcher(API),live)
    print('Riot live:',live,'Data source newest:',source,flush=True)
    manifest={'format':'rift-draft-manifest','schema_version':1,
              'generated_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
              'riot_patch':live,'source_patch':source,'source_fresh':live==source,
              'assets_version':version,'provider':REPO,'recent':{},'history':{}}
    for role in ROLES:
        for kind in ('recent','history'):
            url=f'{RAW}/snapshots/{source}/{role}.json' if kind=='recent' else f'{RAW}/weighted/{role}.json'
            rel=Path('data')/kind/(role+'.json');dst=site/rel
            try:
                obj=fetcher(url)
                if not validate(obj,role,source,kind):
                    raise ValueError('dataset schema or patch mismatch')
                digest=atomic_json(dst,obj)
                manifest[kind][role]={'available':True,'sha256':digest,
                                      'updated_at':obj.get('scraped_at') or obj.get('generated_at')}
                print('✓',kind,role,'validated',flush=True)
            except Exception as exc:
                print('WARNING:',kind,role,exc,file=sys.stderr)
                # Preserve existing good files from earlier sync runs ONLY if
                # their patch is still correct. Never mislabel an old patch.
                try:
                    old=json.loads(dst.read_text(encoding='utf-8'))
                    if not validate(old,role,source,kind):raise ValueError('stale old file')
                    digest=sha256(dst.read_bytes()).hexdigest()
                    manifest[kind][role]={'available':True,'sha256':digest,
                                          'updated_at':old.get('scraped_at') or old.get('generated_at'),
                                          'retained_from_previous_build':True}
                except Exception:
                    dst.unlink(missing_ok=True)
                    manifest[kind][role]={'available':False,'error':'Upstream unavailable or invalid'}
    count=sum(manifest[k][r]['available'] for k in ('recent','history') for r in ROLES)
    if count==0: raise RuntimeError('All upstream data unavailable; refusing empty deployment')
    atomic_json(site/'data'/'manifest.json',manifest)
    print('Published',count,'/10 source files. Manifest patch',source,flush=True)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site',type=Path,default=Path(__file__).resolve().parents[1]/'site')
    args=parser.parse_args()
    build(args.site)


if __name__=='__main__':main()
