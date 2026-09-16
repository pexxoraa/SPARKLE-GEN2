import unittest
from sparkle_gen2.oauth_connectors import OAuthConnectorAdapter
class Transport:
    def __init__(self):self.connections={};self.secret_seen=None
    def connect(self,p,a,s,scopes):self.secret_seen=s;self.connections['c1']={'provider':p,'account':a,'scopes':scopes};return {'connection_id':'c1','metadata':{'tenant':'opaque'}}
    def health(self,c):return {'ok':c in self.connections}
    def invoke(self,c,o,p):return {'connection_id':c,'operation':o,'payload':p}
    def verify(self,c,o,r):return {'verified':r['connection_id']==c and r['operation']==o,'method':'provider_reread'}
    def revoke(self,c):self.connections.pop(c,None);return {'revoked':True}
class Cycle32Tests(unittest.TestCase):
    def test_oauth_adapter_uses_secret_reference_scope_bounds_verify_and_revoke(self):
        t=Transport();a=OAuthConnectorAdapter('gmail',['gmail.read'],t);public=a.authorize('acct-ref','vault://gmail/user',['gmail.read']);self.assertNotIn('secret',str(public).lower());self.assertEqual(t.secret_seen,'vault://gmail/user');self.assertTrue(a.health()['ok']);r=a.invoke('search',{'q':'x'});self.assertTrue(a.verify('search',r)['verified']);self.assertTrue(a.revoke()['revoked']);self.assertFalse(a.health()['ok'])
    def test_oauth_adapter_rejects_undeclared_scope_and_missing_secret_reference(self):
        a=OAuthConnectorAdapter('drive',['drive.read'],Transport())
        with self.assertRaises(PermissionError):a.authorize('a','vault://x',['drive.write'])
        with self.assertRaises(ValueError):a.authorize('a','',['drive.read'])
if __name__=='__main__':unittest.main()
