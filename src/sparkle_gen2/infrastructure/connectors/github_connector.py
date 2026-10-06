from __future__ import annotations
import hashlib,json,os,re,socket,stat
from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Any,Callable
from urllib.parse import quote,urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

GITHUB_SECRET_REF='SPARKLE_GITHUB_TOKEN_FILE'
API_ROOT='https://api.github.com'
API_VERSION='2022-11-28'
ACCEPT='application/vnd.github+json'
MAX_RESPONSE_BYTES=2_000_000
MAX_REPOS=25;DEFAULT_REPOS=10
MAX_CONTENTS=50;DEFAULT_CONTENTS=20
MAX_LIST=25;DEFAULT_LIST=10
MAX_NAME=512;MAX_LOGIN=256;MAX_PATH=1024;MAX_QUERY=256
ID_RE=re.compile(r'^[0-9]{1,32}$')
SHA_RE=re.compile(r'^[0-9a-fA-F]{7,64}$')
REPO_RE=re.compile(r'^[A-Za-z0-9_.-]{1,100}$')
LOGIN_RE=re.compile(r'^[A-Za-z0-9-]{1,256}$')

class GitHubConnectorError(RuntimeError):
    def __init__(self,category:str,message:str):super().__init__(message);self.category=category

@dataclass(frozen=True,slots=True)
class GitHubUser:
    user_id:int;login:str;account_type:str
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class GitHubRepositorySummary:
    repository_id:int;owner:str;name:str;full_name:str;private:bool;updated_at:str|None;default_branch:str|None
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class GitHubRepositoryList:
    repositories:tuple[GitHubRepositorySummary,...];result_count:int;has_more:bool
    def to_dict(self):return {'repositories':[x.to_dict() for x in self.repositories],'result_count':self.result_count,'has_more':self.has_more}
@dataclass(frozen=True,slots=True)
class GitHubRepositoryMetadata:
    repository_id:int;owner:str;name:str;full_name:str;private:bool;updated_at:str|None;default_branch:str|None;archived:bool;disabled:bool
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class GitHubContentSummary:
    path:str;name:str;content_type:str;size_bytes:int|None;sha:str|None
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class GitHubContentList:
    items:tuple[GitHubContentSummary,...];result_count:int;truncated:bool
    def to_dict(self):return {'items':[x.to_dict() for x in self.items],'result_count':self.result_count,'truncated':self.truncated}
@dataclass(frozen=True,slots=True)
class GitHubIssueSummary:
    issue_id:int;number:int;state:str;title:str;updated_at:str|None
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class GitHubIssueList:
    issues:tuple[GitHubIssueSummary,...];result_count:int;has_more:bool
    def to_dict(self):return {'issues':[x.to_dict() for x in self.issues],'result_count':self.result_count,'has_more':self.has_more}
@dataclass(frozen=True,slots=True)
class GitHubPullRequestSummary:
    pull_request_id:int;number:int;state:str;title:str;updated_at:str|None;draft:bool
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class GitHubPullRequestList:
    pull_requests:tuple[GitHubPullRequestSummary,...];result_count:int;has_more:bool
    def to_dict(self):return {'pull_requests':[x.to_dict() for x in self.pull_requests],'result_count':self.result_count,'has_more':self.has_more}
@dataclass(frozen=True,slots=True)
class GitHubWorkflowSummary:
    workflow_id:int;name:str;path:str;state:str
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class GitHubWorkflowList:
    workflows:tuple[GitHubWorkflowSummary,...];result_count:int;total_count:int
    def to_dict(self):return {'workflows':[x.to_dict() for x in self.workflows],'result_count':self.result_count,'total_count':self.total_count}

class GitHubCredentialSource:
    def __init__(self,*,secret_ref=GITHUB_SECRET_REF,path:Path|str|None=None):
        self.secret_ref=secret_ref;configured=os.environ.get(secret_ref);self._path=Path(path).expanduser() if path is not None else (Path(configured).expanduser() if configured else None)
    def configured(self)->bool:
        if self._path is None:return False
        try:
            if not self._path.is_file() or self._path.is_symlink():return False
            return stat.S_IMODE(self._path.stat().st_mode)&0o077==0
        except OSError:return False
    def load(self)->str:
        if not self.configured():raise GitHubConnectorError('AUTH_REQUIRED','GitHub credential reference is not configured')
        try:data=json.loads(self._path.read_text())
        except Exception as exc:raise GitHubConnectorError('AUTH_REQUIRED','GitHub credential could not be loaded') from exc
        token=data.get('token') if isinstance(data,dict) else None
        if not isinstance(token,str) or not token.strip() or len(token)>512:raise GitHubConnectorError('AUTH_REQUIRED','GitHub credential is invalid')
        return token.strip()

class GitHubReadAdapter:
    provider='GitHub API'
    def __init__(self,credential_source:GitHubCredentialSource|None=None,*,opener:Callable[...,Any]|None=None):self.credentials=credential_source or GitHubCredentialSource();self._opener=opener or urlopen;self._token=None;self._account_ref=None
    def configured(self):return self.credentials.configured()
    @staticmethod
    def _max(value,default,maximum):
        if value is None:return default
        if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=maximum:raise ValueError(f'max_results must be 1..{maximum}')
        return value
    @staticmethod
    def _owner_repo(owner,repo):
        if not isinstance(owner,str) or not LOGIN_RE.fullmatch(owner):raise ValueError('invalid GitHub owner')
        if not isinstance(repo,str) or not REPO_RE.fullmatch(repo):raise ValueError('invalid GitHub repository name')
        return owner,repo
    @staticmethod
    def _path(value):
        if value is None:return ''
        if not isinstance(value,str) or len(value)>MAX_PATH or '\x00' in value or value.startswith('/') or '..' in value.split('/'):raise ValueError('invalid GitHub repository path')
        return value.strip('/')
    @staticmethod
    def _query(value):
        if value is None:return None
        if not isinstance(value,str) or not value.strip() or len(value)>MAX_QUERY or any(ord(c)<32 for c in value):raise ValueError('invalid GitHub repository query')
        return value.strip().lower()
    @staticmethod
    def _id(value,label='id'):
        if isinstance(value,bool) or not isinstance(value,int) or value<1:raise GitHubConnectorError('MALFORMED_RESPONSE',f'GitHub {label} is malformed')
        return value
    @staticmethod
    def _text(value,label,max_len=MAX_NAME,allow_empty=False):
        if not isinstance(value,str) or len(value)>max_len or (not allow_empty and not value):raise GitHubConnectorError('MALFORMED_RESPONSE',f'GitHub {label} is malformed')
        return value
    def _request(self,path,params=None):
        if self._token is None:self._token=self.credentials.load()
        url=API_ROOT+path+(('?'+urlencode(params,doseq=True)) if params else '')
        req=Request(url,headers={'Accept':ACCEPT,'X-GitHub-Api-Version':API_VERSION,'Authorization':'Bearer '+self._token,'User-Agent':'SPARKLE-Gen2'})
        try:
            with self._opener(req,timeout=20) as resp:
                raw=resp.read(MAX_RESPONSE_BYTES+1)
                if len(raw)>MAX_RESPONSE_BYTES:raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub response exceeds bound')
        except HTTPError as exc:
            status=int(getattr(exc,'code',0) or 0)
            try:exc.close()
            except Exception:pass
            category='AUTH_REVOKED' if status==401 else ('GITHUB_FORBIDDEN' if status==403 else ('GITHUB_NOT_FOUND' if status==404 else ('GITHUB_RATE_LIMIT' if status==429 else 'GITHUB_API_ERROR')));raise GitHubConnectorError(category,'GitHub API request failed') from exc
        except (socket.timeout,TimeoutError) as exc:raise GitHubConnectorError('TIMEOUT','GitHub API request timed out') from exc
        except URLError as exc:
            if isinstance(getattr(exc,'reason',None),(socket.timeout,TimeoutError)):raise GitHubConnectorError('TIMEOUT','GitHub API request timed out') from exc
            raise GitHubConnectorError('GITHUB_API_ERROR','GitHub API transport failed') from exc
        try:return json.loads(raw.decode('utf-8'))
        except Exception as exc:raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub response is not valid JSON') from exc
    @classmethod
    def _user(cls,x):
        if not isinstance(x,dict):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub user is malformed')
        uid=cls._id(x.get('id'),'user id');login=cls._text(x.get('login'),'login',MAX_LOGIN);typ=cls._text(x.get('type'),'account type',64);return GitHubUser(uid,login,typ)
    @classmethod
    def _repo(cls,x,metadata=False):
        if not isinstance(x,dict) or not isinstance(x.get('owner'),dict):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub repository is malformed')
        rid=cls._id(x.get('id'),'repository id');owner=cls._text(x['owner'].get('login'),'repository owner',MAX_LOGIN);name=cls._text(x.get('name'),'repository name',100);full=cls._text(x.get('full_name'),'repository full_name',300)
        if full!=owner+'/'+name:raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub repository identity is inconsistent')
        private=x.get('private');
        if not isinstance(private,bool):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub repository privacy state is malformed')
        updated=x.get('updated_at');branch=x.get('default_branch')
        if updated is not None:cls._text(updated,'repository updated_at',64)
        if branch is not None:cls._text(branch,'default branch',255)
        if metadata:
            archived=x.get('archived',False);disabled=x.get('disabled',False)
            if not isinstance(archived,bool) or not isinstance(disabled,bool):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub repository status flags are malformed')
            return GitHubRepositoryMetadata(rid,owner,name,full,private,updated,branch,archived,disabled)
        return GitHubRepositorySummary(rid,owner,name,full,private,updated,branch)
    @classmethod
    def _content(cls,x):
        if not isinstance(x,dict):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub content item is malformed')
        path=cls._text(x.get('path'),'content path',MAX_PATH);name=cls._text(x.get('name'),'content name',MAX_NAME);typ=cls._text(x.get('type'),'content type',32)
        if typ not in {'file','dir','symlink','submodule'}:raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub content type is unsupported')
        size=x.get('size');
        if size is not None and (isinstance(size,bool) or not isinstance(size,int) or size<0):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub content size is malformed')
        sha=x.get('sha');
        if sha is not None and (not isinstance(sha,str) or not SHA_RE.fullmatch(sha)):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub content sha is malformed')
        return GitHubContentSummary(path,name,typ,size,sha)
    @classmethod
    def _issue(cls,x):
        if not isinstance(x,dict):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub issue is malformed')
        iid=cls._id(x.get('id'),'issue id');num=cls._id(x.get('number'),'issue number');state=cls._text(x.get('state'),'issue state',32);title=cls._text(x.get('title'),'issue title',512);updated=x.get('updated_at')
        if updated is not None:cls._text(updated,'issue updated_at',64)
        return GitHubIssueSummary(iid,num,state,title,updated)
    @classmethod
    def _pull(cls,x):
        if not isinstance(x,dict):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub pull request is malformed')
        pid=cls._id(x.get('id'),'pull request id');num=cls._id(x.get('number'),'pull request number');state=cls._text(x.get('state'),'pull request state',32);title=cls._text(x.get('title'),'pull request title',512);updated=x.get('updated_at');draft=x.get('draft',False)
        if updated is not None:cls._text(updated,'pull request updated_at',64)
        if not isinstance(draft,bool):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub pull request draft state is malformed')
        return GitHubPullRequestSummary(pid,num,state,title,updated,draft)
    @classmethod
    def _workflow(cls,x):
        if not isinstance(x,dict):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub workflow is malformed')
        wid=cls._id(x.get('id'),'workflow id');name=cls._text(x.get('name'),'workflow name',512);path=cls._text(x.get('path'),'workflow path',MAX_PATH);state=cls._text(x.get('state'),'workflow state',64);return GitHubWorkflowSummary(wid,name,path,state)
    @staticmethod
    def _ref_id(kind,value):return kind+':'+hashlib.sha256(str(value).encode()).hexdigest()[:32]
    def authorize(self):
        self._token=self.credentials.load();u=self._user(self._request('/user'));self._account_ref=self._ref_id('github-user',u.user_id);return {'authorization_reference':self._account_ref,'account_ref':self._account_ref,'granted_scopes':['github.read'],'secret_ref':self.credentials.secret_ref}
    def health(self):
        if not self.configured():return {'ok':False,'status':'AUTH_REQUIRED','authorization_state':'NOT_CONFIGURED','provider':self.provider,'secret_ref':self.credentials.secret_ref}
        try:
            self._token=self.credentials.load();u=self._user(self._request('/user'));ref=self._ref_id('github-user',u.user_id);self._account_ref=ref;return {'ok':True,'status':'HEALTHY','authorization_state':'AUTHORIZED','provider':self.provider,'account_ref':ref}
        except GitHubConnectorError as exc:
            auth='REVOKED' if exc.category=='AUTH_REVOKED' else ('REQUIRED' if exc.category=='AUTH_REQUIRED' else 'FAILED');return {'ok':False,'status':exc.category,'authorization_state':auth,'provider':self.provider,'error_category':exc.category,'secret_ref':self.credentials.secret_ref}
    def _ready(self):
        if self._account_ref is None:self.authorize()
        return self._account_ref
    def invoke(self,operation,payload):
        account=self._ready();p=dict(payload or {})
        if operation=='get_user':
            if p:raise ValueError('get_user accepts no arguments')
            u=self._user(self._request('/user'));return {'provider':self.provider,'operation':operation,'account_ref':account,'result':u.to_dict(),'provider_reference':'github:user.get'}
        if operation=='list_repositories':
            if set(p)-{'max_results','query'}:raise ValueError('unsupported repository-list argument')
            maximum=self._max(p.get('max_results'),DEFAULT_REPOS,MAX_REPOS);query=self._query(p.get('query'));raw=self._request('/user/repos',{'per_page':maximum,'sort':'updated','direction':'desc','affiliation':'owner,collaborator,organization_member'})
            if not isinstance(raw,list):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub repository list is malformed')
            repos=[self._repo(x) for x in raw]
            if query is not None:repos=[r for r in repos if query in r.name.lower() or query in r.full_name.lower()]
            repos=repos[:maximum];return {'provider':self.provider,'operation':operation,'account_ref':account,'result':GitHubRepositoryList(tuple(repos),len(repos),len(raw)>=maximum).to_dict(),'provider_reference':'github:user.repos'}
        owner,repo=self._owner_repo(p.get('owner'),p.get('repo')) if operation!='get_user' else (None,None)
        base=f'/repos/{quote(owner,safe="")}/{quote(repo,safe="")}'
        if operation=='get_repository':
            if set(p)-{'owner','repo'}:raise ValueError('unsupported repository argument')
            r=self._repo(self._request(base),metadata=True);return {'provider':self.provider,'operation':operation,'account_ref':account,'result':r.to_dict(),'provider_reference':'github:repos.get'}
        if operation=='list_repository_contents':
            if set(p)-{'owner','repo','path','max_results','ref'}:raise ValueError('unsupported contents argument')
            maximum=self._max(p.get('max_results'),DEFAULT_CONTENTS,MAX_CONTENTS);path=self._path(p.get('path'));ref=p.get('ref')
            if ref is not None:self._text(ref,'content ref',255)
            endpoint=base+'/contents'+(('/'+quote(path,safe='/')) if path else '');raw=self._request(endpoint,{'ref':ref} if ref else None);items=raw if isinstance(raw,list) else [raw]
            parsed=[self._content(x) for x in items[:maximum]];return {'provider':self.provider,'operation':operation,'account_ref':account,'owner':owner,'repo':repo,'path':path,'ref':ref,'result':GitHubContentList(tuple(parsed),len(parsed),len(items)>maximum).to_dict(),'provider_reference':'github:repos.contents'}
        if operation=='list_issues':
            if set(p)-{'owner','repo','max_results','state'}:raise ValueError('unsupported issue-list argument')
            maximum=self._max(p.get('max_results'),DEFAULT_LIST,MAX_LIST);state=p.get('state','open')
            if state not in {'open','closed','all'}:raise ValueError('invalid issue state')
            raw=self._request(base+'/issues',{'per_page':maximum,'state':state,'sort':'updated','direction':'desc'});items=[x for x in raw if isinstance(x,dict) and 'pull_request' not in x] if isinstance(raw,list) else None
            if items is None:raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub issue list is malformed')
            issues=tuple(self._issue(x) for x in items[:maximum]);return {'provider':self.provider,'operation':operation,'account_ref':account,'owner':owner,'repo':repo,'result':GitHubIssueList(issues,len(issues),len(raw)>=maximum).to_dict(),'provider_reference':'github:repos.issues'}
        if operation=='list_pull_requests':
            if set(p)-{'owner','repo','max_results','state'}:raise ValueError('unsupported pull-request argument')
            maximum=self._max(p.get('max_results'),DEFAULT_LIST,MAX_LIST);state=p.get('state','open')
            if state not in {'open','closed','all'}:raise ValueError('invalid pull request state')
            raw=self._request(base+'/pulls',{'per_page':maximum,'state':state,'sort':'updated','direction':'desc'});
            if not isinstance(raw,list):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub pull request list is malformed')
            pulls=tuple(self._pull(x) for x in raw[:maximum]);return {'provider':self.provider,'operation':operation,'account_ref':account,'owner':owner,'repo':repo,'result':GitHubPullRequestList(pulls,len(pulls),len(raw)>=maximum).to_dict(),'provider_reference':'github:repos.pulls'}
        if operation=='list_workflows':
            if set(p)-{'owner','repo','max_results'}:raise ValueError('unsupported workflow-list argument')
            maximum=self._max(p.get('max_results'),DEFAULT_LIST,MAX_LIST);raw=self._request(base+'/actions/workflows',{'per_page':maximum})
            if not isinstance(raw,dict) or not isinstance(raw.get('workflows'),list):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub workflow list is malformed')
            flows=tuple(self._workflow(x) for x in raw['workflows'][:maximum]);total=raw.get('total_count')
            if isinstance(total,bool) or not isinstance(total,int) or total<0:raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub workflow total is malformed')
            return {'provider':self.provider,'operation':operation,'account_ref':account,'owner':owner,'repo':repo,'result':GitHubWorkflowList(flows,len(flows),total).to_dict(),'provider_reference':'github:repos.workflows'}
        raise KeyError(operation)
    @staticmethod
    def _digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def _tree_for_path(self,owner,repo,ref,path):
        treeish=ref
        if not treeish:
            meta=self._repo(self._request(f"/repos/{quote(owner,safe='')}/{quote(repo,safe='')}"),metadata=True);treeish=meta.default_branch
        tree=self._request(f"/repos/{quote(owner,safe='')}/{quote(repo,safe='')}/git/trees/{quote(treeish,safe='')}")
        if not isinstance(tree,dict) or not isinstance(tree.get('tree'),list):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub tree response is malformed')
        if not path:return tree
        for component in path.split('/'):
            entry=next((x for x in tree['tree'] if isinstance(x,dict) and x.get('path')==component and x.get('type')=='tree' and isinstance(x.get('sha'),str)),None)
            if entry is None:raise GitHubConnectorError('VERIFICATION_FAILURE','GitHub content directory is absent from tree reread')
            tree=self._request(f"/repos/{quote(owner,safe='')}/{quote(repo,safe='')}/git/trees/{quote(entry['sha'],safe='')}")
            if not isinstance(tree,dict) or not isinstance(tree.get('tree'),list):raise GitHubConnectorError('MALFORMED_RESPONSE','GitHub nested tree response is malformed')
        return tree
    def verify(self,operation,result):
        if not isinstance(result,dict) or result.get('provider')!=self.provider or result.get('operation')!=operation:return {'verified':False,'reason':'provider_or_operation_mismatch','method':'GitHub provider reread'}
        u=self._user(self._request('/user'));account=self._ref_id('github-user',u.user_id)
        if result.get('account_ref')!=account or (self._account_ref is not None and account!=self._account_ref):return {'verified':False,'reason':'authorized_account_identity_mismatch','method':'GitHub authenticated-user reread'}
        v=result.get('result')
        if operation=='get_user':
            again=u.to_dict();return {'verified':self._digest(again)==self._digest(v),'method':'GitHub authenticated-user exact reread','provider':self.provider,'account_ref':account,'user_id_hash':hashlib.sha256(str(u.user_id).encode()).hexdigest()[:20]}
        if operation=='list_repositories':
            if not isinstance(v,dict) or not isinstance(v.get('repositories'),list) or v.get('result_count')!=len(v['repositories']):return {'verified':False,'reason':'repository_list_schema_invalid','method':'GitHub repository reread'}
            hashes=[]
            for x in v['repositories']:
                r=self._repo({'id':x.get('repository_id'),'owner':{'login':x.get('owner')},'name':x.get('name'),'full_name':x.get('full_name'),'private':x.get('private'),'updated_at':x.get('updated_at'),'default_branch':x.get('default_branch')});hashes.append(hashlib.sha256(str(r.repository_id).encode()).hexdigest()[:20])
            if v['repositories']:
                x=v['repositories'][0];again=self._repo(self._request(f"/repos/{quote(x['owner'],safe='')}/{quote(x['name'],safe='')}"))
                if again.repository_id!=x['repository_id'] or again.name!=x['name'] or again.owner!=x['owner']:return {'verified':False,'reason':'repository_identity_reread_mismatch','method':'GitHub repository reread'}
            return {'verified':True,'method':'GitHub authenticated identity + selected repository reread','provider':self.provider,'account_ref':account,'result_count':len(v['repositories']),'repository_id_hashes':hashes}
        if operation=='get_repository':
            if not isinstance(v,dict):return {'verified':False,'reason':'repository_schema_invalid','method':'GitHub exact repository reread'}
            again=self._repo(self._request(f"/repos/{quote(v['owner'],safe='')}/{quote(v['name'],safe='')}"),metadata=True).to_dict();ok=self._digest(again)==self._digest(v);return {'verified':ok,'method':'GitHub exact repository reread','provider':self.provider,'account_ref':account,'metadata_sha256':self._digest(v) if ok else None,'repository_id_hash':hashlib.sha256(str(v.get('repository_id')).encode()).hexdigest()[:20]}
        if operation=='list_repository_contents':
            if not isinstance(v,dict) or not isinstance(v.get('items'),list) or v.get('result_count')!=len(v['items']):return {'verified':False,'reason':'contents_schema_invalid','method':'GitHub tree metadata reread'}
            owner,repo=self._owner_repo(result.get('owner'),result.get('repo'));path=self._path(result.get('path'));hashes=[]
            for x in v['items']:
                c=self._content({'path':x.get('path'),'name':x.get('name'),'type':x.get('content_type'),'size':x.get('size_bytes'),'sha':x.get('sha')});hashes.append(hashlib.sha256(c.path.encode()).hexdigest()[:20])
            if v['items']:
                try:tree=self._tree_for_path(owner,repo,result.get('ref'),path)
                except GitHubConnectorError:return {'verified':False,'reason':'contents_tree_reread_failed','method':'GitHub tree metadata reread'}
                first=v['items'][0];target_name=first['path'].split('/')[-1];match=next((x for x in tree['tree'] if isinstance(x,dict) and x.get('path')==target_name),None);expected_type={'file':'blob','dir':'tree','symlink':'blob','submodule':'commit'}.get(first.get('content_type'))
                if match is None or match.get('sha')!=first.get('sha') or (expected_type and match.get('type')!=expected_type):return {'verified':False,'reason':'contents_identity_reread_mismatch','method':'GitHub tree metadata reread'}
            return {'verified':True,'method':'GitHub authenticated identity + Git tree metadata reread','provider':self.provider,'account_ref':account,'result_count':len(v['items']),'path_hashes':hashes}
        if operation in {'list_issues','list_pull_requests','list_workflows'}:
            key={'list_issues':'issues','list_pull_requests':'pull_requests','list_workflows':'workflows'}[operation]
            if not isinstance(v,dict) or not isinstance(v.get(key),list) or v.get('result_count')!=len(v[key]):return {'verified':False,'reason':'list_schema_invalid','method':'GitHub selected-item reread'}
            owner,repo=self._owner_repo(result.get('owner'),result.get('repo'));ids=[];id_key={'list_issues':'issue_id','list_pull_requests':'pull_request_id','list_workflows':'workflow_id'}[operation]
            for x in v[key]:ids.append(hashlib.sha256(str(self._id(x.get(id_key),id_key)).encode()).hexdigest()[:20])
            if v[key]:
                first=v[key][0]
                if operation=='list_issues':
                    raw=self._request(f"/repos/{quote(owner,safe='')}/{quote(repo,safe='')}/issues/{first['number']}");again=self._issue(raw);ok=again.issue_id==first['issue_id'] and again.number==first['number'] and again.state==first['state']
                elif operation=='list_pull_requests':
                    raw=self._request(f"/repos/{quote(owner,safe='')}/{quote(repo,safe='')}/pulls/{first['number']}");again=self._pull(raw);ok=again.pull_request_id==first['pull_request_id'] and again.number==first['number'] and again.state==first['state']
                else:
                    raw=self._request(f"/repos/{quote(owner,safe='')}/{quote(repo,safe='')}/actions/workflows/{first['workflow_id']}");again=self._workflow(raw);ok=again.workflow_id==first['workflow_id'] and again.path==first['path'] and again.state==first['state']
                if not ok:return {'verified':False,'reason':'selected_item_reread_mismatch','method':'GitHub selected-item reread'}
            return {'verified':True,'method':'GitHub authenticated identity + selected-item reread','provider':self.provider,'account_ref':account,'result_count':len(v[key]),'item_id_hashes':ids}
        return {'verified':False,'reason':'unsupported_operation','method':'GitHub provider reread'}
