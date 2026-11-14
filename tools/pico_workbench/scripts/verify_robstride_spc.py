"""Offline provenance and build verification. Never opens serial or ST-LINK."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'projects/pico-firmware/firmware/PICO_CAN/App/vendor/robstride_spc'

def verify_sources():
    meta=json.loads((BASE/'SOURCE.json').read_text(encoding='utf-8'))
    assert meta['commit']=='d8451a447d7265becf71271a008a71f7063b7ecc'
    for name,record in meta['upstream_files'].items():
        raw=(BASE/'upstream'/name).read_bytes()
        blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        assert blob==record['git_blob_sha1'],f'Upstream Git blob mismatch: {name}'
        assert hashlib.sha256(raw).hexdigest()==record['sha256'],f'Upstream SHA256 mismatch: {name}'
    return meta

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--builds',action='store_true');args=parser.parse_args()
    meta=verify_sources();result={'source_commit':meta['commit'],'upstream_files_verified':len(meta['upstream_files']),'hardware_access':False}
    if args.builds:
        sys.path.insert(0,str(ROOT/'ui'));import catalog,platform_tools as tools
        rows=[]
        for profile in catalog.builtins():
            if not profile.get('cmake_options',{}).get('PICO_APP','').startswith('Motor'):continue
            image=tools.image_for(profile['id']);raw=image.read_bytes()
            assert b'CONTROL_BACKEND,library=RobStrideSPC,commit='+meta['commit'].encode() in raw,profile['id']
            built=json.loads((tools.build_dir(profile['id'])/'ui_build_profile.json').read_text(encoding='utf-8'))
            assert built['profile']==profile,f'Build/profile mismatch: {profile["id"]}'
            assert not tools.source_newer(image,profile['id']),f'Build is stale: {profile["id"]}'
            rows.append({'profile':profile['id'],'image':str(image),'sha256':hashlib.sha256(raw).hexdigest()})
        result['builds_verified']=rows
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
