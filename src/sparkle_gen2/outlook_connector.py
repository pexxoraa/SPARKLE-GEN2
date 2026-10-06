from __future__ import annotations
import hashlib,json,socket
from urllib.parse import urlencode,quote
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

MAX_RESULTS=25;DEFAULT_RESULTS=5;MAX_TEXT=2000;MAX_BODY=20000;MAX_RECIPIENTS=20
class OutlookConnectorError(RuntimeError):
    def __init__(self,category,message):super().__init__(message);self.category=category

class OutlookCredentialSource:
    def __init__(self,secrets,secret_ref='MICROSOFT_GRAPH_TOKEN'):self.secrets=secrets;self.secret_ref=secret_ref
    def configured(self):
        try:return bool(self.secrets.status([self.secret_ref]).get(self.secret_ref))
        except Exception:return False
    def load(self):
        if not self.configured():raise OutlookConnectorError('AUTH_REQUIRED','Microsoft Graph credential is not configured')
        try:return self.secrets.first([self.secret_ref])
        except Exception as exc:raise OutlookConnectorError('AUTH_REQUIRED','Microsoft Graph credential is unavailable') from exc

class OutlookGraphAdapter:
    provider='Microsoft Graph'
    BASE='https://graph.microsoft.com/v1.0'
    def __init__(self,credential_source,*,opener=None,timeout=20):self.credentials=credential_source;self._opener=opener or urlopen;self.timeout=min(max(float(timeout),1),60);self._account_ref=None
    def configured(self):return self.credentials.configured()
    def _request(self,method,path,payload=None,query=None):
        token=self.credentials.load();url=self.BASE+path+((('?'+urlencode(query)) if query else ''));body=None if payload is None else json.dumps(payload,separators=(',',':')).encode();req=Request(url,data=body,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/json','Content-Type':'application/json','Prefer':'IdType="ImmutableId"','User-Agent':'SPARKLE/0.30'})
        try:
            with self._opener(req,timeout=self.timeout) as r:raw=r.read();status=getattr(r,'status',200)
        except HTTPError as exc:
            cat='AUTH_REVOKED' if exc.code==401 else ('RATE_LIMIT' if exc.code==429 else 'GRAPH_API_ERROR');raise OutlookConnectorError(cat,'Microsoft Graph request failed') from exc
        except (URLError,socket.timeout,TimeoutError) as exc:raise OutlookConnectorError('TIMEOUT','Microsoft Graph request timed out') from exc
        if status==202 and not raw:return {'accepted':True}
        try:return json.loads(raw.decode()) if raw else {}
        except Exception as exc:raise OutlookConnectorError('MALFORMED_RESPONSE','Microsoft Graph returned malformed JSON') from exc
    @staticmethod
    def _ref(value):return 'outlook:'+hashlib.sha256(str(value).encode()).hexdigest()[:32]
    def authorize(self):
        me=self._request('GET','/me',query={'$select':'id'});mid=me.get('id') if isinstance(me,dict) else None
        if not isinstance(mid,str) or not mid:raise OutlookConnectorError('MALFORMED_RESPONSE','Microsoft account identity malformed')
        self._account_ref=self._ref(mid);return {'authorization_reference':self._account_ref,'granted_scopes':['outlook.read','outlook.draft','outlook.send']}
    def health(self):
        if not self.configured():return {'ok':False,'status':'AUTH_REQUIRED','authorization_state':'NOT_CONFIGURED','provider':self.provider}
        try:self.authorize();return {'ok':True,'status':'HEALTHY','authorization_state':'AUTHORIZED','provider':self.provider,'account_ref':self._account_ref}
        except OutlookConnectorError as exc:return {'ok':False,'status':exc.category,'authorization_state':'REVOKED' if exc.category=='AUTH_REVOKED' else 'FAILED','provider':self.provider,'error_category':exc.category}
    @staticmethod
    def _msg(x):
        if not isinstance(x,dict) or not isinstance(x.get('id'),str) or not x['id']:raise OutlookConnectorError('MALFORMED_RESPONSE','Outlook message identity malformed')
        return {'message_ref':OutlookGraphAdapter._ref(x['id']),'provider_id':x['id'],'conversation_ref':OutlookGraphAdapter._ref(x.get('conversationId','')) if x.get('conversationId') else None,'subject':str(x.get('subject') or '')[:MAX_TEXT],'received_at':x.get('receivedDateTime'),'is_read':bool(x.get('isRead',False)),'is_draft':bool(x.get('isDraft',False))}
    def _ready(self):
        if self._account_ref is None:self.authorize()
    def invoke(self,operation,payload):
        self._ready();p=dict(payload or {})
        if operation=='read':
            if set(p)-{'max_results'}:raise ValueError('unsupported Outlook read argument')
            n=p.get('max_results',DEFAULT_RESULTS)
            if isinstance(n,bool) or not isinstance(n,int) or not 1<=n<=MAX_RESULTS:raise ValueError('max_results must be 1..25')
            raw=self._request('GET','/me/messages',query={'$top':n,'$select':'id,conversationId,subject,receivedDateTime,isRead,isDraft','$orderby':'receivedDateTime desc'});vals=raw.get('value') if isinstance(raw,dict) else None
            if not isinstance(vals,list) or len(vals)>n:raise OutlookConnectorError('MALFORMED_RESPONSE','Outlook message list malformed')
            return {'provider':self.provider,'operation':operation,'account_ref':self._account_ref,'result':{'messages':[self._msg(x) for x in vals],'result_count':len(vals)},'provider_reference':'graph:me.messages'}
        if operation=='draft':
            allowed={'subject','body','to'}
            if set(p)-allowed:raise ValueError('unsupported Outlook draft argument')
            subject=str(p.get('subject') or '').strip();body=str(p.get('body') or '');recipients=p.get('to') or []
            if not subject or len(subject)>MAX_TEXT or len(body)>MAX_BODY or not isinstance(recipients,list) or not 1<=len(recipients)<=MAX_RECIPIENTS:raise ValueError('Outlook draft payload invalid')
            tos=[]
            for addr in recipients:
                if not isinstance(addr,str) or not addr.strip() or len(addr)>320 or '@' not in addr:raise ValueError('Outlook recipient invalid')
                tos.append({'emailAddress':{'address':addr.strip()}})
            raw=self._request('POST','/me/messages',{'subject':subject,'body':{'contentType':'Text','content':body},'toRecipients':tos});msg=self._msg(raw)
            return {'provider':self.provider,'operation':operation,'account_ref':self._account_ref,'result':{'message_ref':msg['message_ref'],'provider_id':msg['provider_id'],'is_draft':msg['is_draft']},'provider_reference':'graph:me.messages.create'}
        if operation=='send':
            if set(p)-{'message_id'}:raise ValueError('unsupported Outlook send argument')
            mid=p.get('message_id')
            if not isinstance(mid,str) or not mid or len(mid)>1024:raise ValueError('Outlook message_id invalid')
            before=self._msg(self._request('GET','/me/messages/'+quote(mid,safe=''),query={'$select':'id,isDraft'}))
            if before['is_draft'] is not True:raise ValueError('Outlook send requires an existing draft')
            accepted=self._request('POST','/me/messages/'+quote(mid,safe='')+'/send',{})
            return {'provider':self.provider,'operation':operation,'account_ref':self._account_ref,'result':{'message_ref':before['message_ref'],'provider_id':mid,'accepted':bool(accepted.get('accepted'))},'provider_reference':'graph:message.send'}
        raise KeyError(operation)
    def verify(self,operation,result):
        if not isinstance(result,dict) or result.get('provider')!=self.provider or result.get('operation')!=operation:return {'verified':False,'reason':'provider_or_operation_mismatch'}
        auth=self.authorize()
        if result.get('account_ref')!=auth['authorization_reference']:return {'verified':False,'reason':'account_mismatch'}
        value=result.get('result') or {}
        if operation=='read':
            msgs=value.get('messages') if isinstance(value,dict) else None
            if not isinstance(msgs,list) or value.get('result_count')!=len(msgs):return {'verified':False,'reason':'read_schema_invalid'}
            if msgs:
                mid=msgs[0].get('provider_id');again=self._msg(self._request('GET','/me/messages/'+quote(mid,safe=''),query={'$select':'id,conversationId,subject,receivedDateTime,isRead,isDraft'}));
                if again['message_ref']!=msgs[0].get('message_ref'):return {'verified':False,'reason':'message_reread_mismatch'}
            return {'verified':True,'method':'Graph account identity + selected message reread','result_count':len(msgs)}
        mid=value.get('provider_id')
        if not isinstance(mid,str):return {'verified':False,'reason':'message_identity_missing'}
        try:again=self._msg(self._request('GET','/me/messages/'+quote(mid,safe=''),query={'$select':'id,isDraft'}))
        except OutlookConnectorError:return {'verified':False,'reason':'message_reread_failed'}
        if operation=='draft':return {'verified':again['message_ref']==value.get('message_ref') and again['is_draft'] is True,'method':'Graph draft reread'}
        if operation=='send':return {'verified':again['message_ref']==value.get('message_ref') and again['is_draft'] is False,'method':'Graph sent-message immutable-id reread'}
        return {'verified':False,'reason':'unsupported_operation'}
