import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class InstallerTests(unittest.TestCase):
 def test_syntax_and_family_plans(self):
  script=ROOT/'install.sh'
  subprocess.run(['bash','-n',str(script)],check=True)
  for distro,like,manager in [('ubuntu','debian','apt'),('zorin','ubuntu debian','apt'),('rocky','rhel fedora','dnf'),('fedora','','dnf'),('opensuse-leap','suse opensuse','zypper'),('arch','','pacman')]:
   with self.subTest(distro=distro),tempfile.TemporaryDirectory() as folder:
    release=Path(folder)/'os-release';release.write_text(f'ID={distro}\nID_LIKE="{like}"\n')
    env=dict(os.environ,Q_INSTALL_OS_RELEASE=str(release))
    output=subprocess.check_output(['bash',str(script),'--plan'],env=env,text=True)
    self.assertIn('gestor='+manager,output)
 def test_reject_unknown_family(self):
  with tempfile.TemporaryDirectory() as folder:
   release=Path(folder)/'os-release';release.write_text('ID=alpine\n')
   result=subprocess.run(['bash',str(ROOT/'install.sh'),'--plan'],env=dict(os.environ,Q_INSTALL_OS_RELEASE=str(release)),capture_output=True,text=True)
   self.assertNotEqual(result.returncode,0)
if __name__=='__main__':unittest.main()
