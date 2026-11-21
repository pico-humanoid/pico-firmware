"""Fetch a fixed official Arm toolchain; verify before extraction (CI only)."""
import argparse,hashlib,os,tarfile,zipfile,urllib.request
from pathlib import Path
VERSION='14.3.rel1'
FILES={
 'linux':('arm-gnu-toolchain-14.3.rel1-x86_64-arm-none-eabi.tar.xz','8f6903f8ceb084d9227b9ef991490413014d991874a1e34074443c2a72b14dbd'),
 'windows':('arm-gnu-toolchain-14.3.rel1-mingw-w64-x86_64-arm-none-eabi.zip','864c0c8815857d68a1bbba2e5e2782255bb922845c71c97636004a3d74f60986')}
def sha256_stream(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def main():
 p=argparse.ArgumentParser();p.add_argument('destination',type=Path);a=p.parse_args();dest=a.destination.resolve();dest.mkdir(parents=True,exist_ok=True)
 name,expected=FILES['windows' if os.name=='nt' else 'linux'];archive=dest/name;root=dest/name.removesuffix('.tar.xz').removesuffix('.zip')
 if not (root/'bin'/('arm-none-eabi-gcc.exe' if os.name=='nt' else 'arm-none-eabi-gcc')).exists():
  url='https://developer.arm.com/-/media/Files/downloads/gnu/'+VERSION+'/binrel/'+name
  if not archive.exists():urllib.request.urlretrieve(url,archive)
  with archive.open('rb') as f:actual=sha256_stream(f)
  if actual!=expected:raise RuntimeError('Official toolchain SHA256 mismatch')
  if name.endswith('.zip'):
   with zipfile.ZipFile(archive) as z:z.extractall(dest)
  else:
   with tarfile.open(archive) as t:
    # Python 3.10 has no extraction filters on older Ubuntu security revisions.
    # Refuse path escapes and special files even after the pinned hash check.
    for member in t.getmembers():
     target=(dest/member.name).resolve()
     if not target.is_relative_to(dest) or member.isdev() or member.isfifo():raise RuntimeError('Unsafe toolchain archive member')
     if member.issym() or member.islnk():
      link=(target.parent/member.linkname if member.issym() else dest/member.linkname).resolve()
      if not link.is_relative_to(dest):raise RuntimeError('Unsafe toolchain archive link')
    t.extractall(dest)
 compiler='arm-none-eabi-gcc.exe' if os.name=='nt' else 'arm-none-eabi-gcc'
 # Official ZIP directory names need not match the download filename.
 candidates=[p for p in dest.rglob(compiler) if p.parent.name=='bin']
 if len(candidates)!=1:raise RuntimeError('Expected one extracted compiler, found: '+str(candidates))
 root=candidates[0].parent.parent
 print('Verified Arm GNU toolchain:',root,flush=True)
 for key,value in [('GITHUB_PATH',str(root/'bin')),('GITHUB_ENV','PICO_ARM_TOOLCHAIN='+str(root))]:
  if os.environ.get(key):
   with open(os.environ[key],'a',encoding='utf-8') as f:f.write(value+'\n')
if __name__=='__main__':main()
