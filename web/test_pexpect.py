import pexpect
import sys

child = pexpect.spawn('bash', encoding='utf-8')
child.expect(r'\$')
child.sendline('echo "Hello World"')
child.expect(r'\$')
print(child.before)
child.sendline('exit')
