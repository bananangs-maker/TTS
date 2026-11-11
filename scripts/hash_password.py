#!/usr/bin/env python3
import getpass,sys
from research_os.app import password_hash
p=getpass.getpass('새 관리자 비밀번호: ')
if not p:raise SystemExit('비밀번호를 입력하세요.')
if p!=getpass.getpass('다시 입력: '):raise SystemExit('일치하지 않습니다.')
print(password_hash(p))
