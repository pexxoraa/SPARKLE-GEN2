from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
from .core import PersonalAgent
from .connector_catalog import build_default_connectors
from .context_sources import PersonalContextAssembler
from .devices import DeviceManager
from .gen1 import LocalGen1Gateway
from .sessions import SessionService
from .personal_data import PersonalDataOrchestrator
from .world_model import WorldModel
from .policy import PolicyEngine
from .storage import Gen2Store
from .environment_gateway import load_environment_gateway
from .document_intelligence import DocumentIntelligenceService
from .image_runtime import ImageGenerationService
from .learning_orchestration import LearningOrchestrator
from .daily_os import DailyOperatingSystemService
from .notifications import NotificationIntelligenceService,NotificationCenter
from .notification_delivery import NotificationDeliveryOrchestrator
from .dashboard import PersonalOperationsService
from .diagnostics import SelfDiagnostics
from .perception import PerceptionService,ROS2PosePerceptionAdapter
from .retrieval import CapabilityRoutedEmbedder,CapabilityRoutedReranker,PersistentSemanticIndex


def data_path()->Path:
    return Path(
        os.environ.get(
            'SPARKLE_GEN2_DB',
            Path.home()/'.local'/'share'/'sparkle-gen2'/'gen2.sqlite3'
        )
    )


def _default_engineering_root()->Path:
    file_path=Path(__file__).resolve()

    for candidate in (
        file_path.parent,
        *file_path.parents,
    ):
        if (
            (candidate/'src'/'sparkle_gen2').is_dir()
            and (candidate/'pyproject.toml').is_file()
        ):
            return candidate

    cwd=Path.cwd().resolve()

    if (cwd/'src'/'sparkle_gen2').is_dir():
        return cwd

    raise RuntimeError('gen2_engineering_root_not_configured')


def build_components(*,activate_external_connectors=False):
    store=Gen2Store(data_path())
    base=LocalGen1Gateway()

    engineering_root=Path(
        os.environ.get(
            'SPARKLE_GEN2_ENGINEERING_ROOT',
            _default_engineering_root()
        )
    ).resolve()

    engineering_db=Path(
        os.environ.get(
            'SPARKLE_GEN2_ENGINEERING_DB',
            data_path().parent/'engineering.sqlite3'
        )
    ).resolve()

    base.bind_engineering_workspace(
        engineering_root,
        engineering_db
    )
    environment_config=Path(
        os.environ.get(
            'SPARKLE_GEN2_ENVIRONMENT_CONFIG',
            Path.home()/'.config'/'sparkle-gen2'/'environment.json'
        )
    )
    gen1=load_environment_gateway(base,environment_config)
    world=WorldModel(store)
    devices=DeviceManager()
    policy=PolicyEngine()
    connectors=build_default_connectors(
        store=store,
        policy=policy,
        gateway=gen1,
        activate_external=activate_external_connectors
    )
    embedder=CapabilityRoutedEmbedder(base.model_manager)
    reranker=(
        CapabilityRoutedReranker(base.model_manager)
        if base.model_manager.status('reranking')['status']=='CONNECTED'
        else None
    )
    semantic_index=PersistentSemanticIndex(
        store,
        embedder,
        reranker=reranker
    )
    context=PersonalContextAssembler(
        personal_data=PersonalDataOrchestrator(gen1),
        connectors=connectors,
        store=store,
        devices=devices,
        world=world,
        semantic_index=semantic_index
    )
    document_root=data_path().parent/'documents'
    document_root.mkdir(parents=True,exist_ok=True)
    documents=DocumentIntelligenceService(
        store,
        allowed_roots=[document_root],
        model_manager=getattr(base,'model_manager',None)
    )
    images=ImageGenerationService(
        store,
        getattr(base,'model_manager',None),
        base
    )
    perception=PerceptionService(
        store,
        world,
        model_manager=getattr(base,'model_manager',None)
    )
    ros2=getattr(gen1,'ros2',None)
    if ros2 is not None:
        perception.register_robot(
            'turtle1',
            device_id='ros2-sim',
            source=ROS2PosePerceptionAdapter(ros2),
            capabilities=['pose']
        )
    learning=LearningOrchestrator(store,gen1)
    daily=DailyOperatingSystemService(store,context)
    notification_center=NotificationCenter(store)
    delivery=NotificationDeliveryOrchestrator(store)
    notifications=NotificationIntelligenceService(
        store,
        center=notification_center,
        delivery=delivery
    )
    delivery.recover_all()
    diagnostics=SelfDiagnostics(
        gen1,
        store=store,
        connectors=context.connectors,
        devices=devices
    )
    operations=PersonalOperationsService(
        store,
        daily_os=daily,
        diagnostics=diagnostics,
        model_manager=getattr(base,'model_manager',None),
        connectors=context.connectors,
        devices=devices,
        world=world,
        notification_service=notifications
    )
    return (
        store,
        PersonalAgent(
            store,
            gen1,
            policy=policy,
            context_provider=context,
            connector_manager=connectors,
            document_service=documents,
            image_service=images,
            perception_service=perception,
            daily_os_service=daily,
            operations_service=operations,
            notification_service=notifications,
            learning_service=learning
        ),
        SessionService(store)
    )


def normalize_request(parts):
    values=list(parts)
    if values and values[0]=='chat':
        values=values[1:]
    return ' '.join(values).strip()


def format_result(result,verbose=False):
    if not verbose:
        return result['text']

    lines=[]
    checked=list(result.get('checked',[]))
    completed=list(result.get('verified',[]))
    approvals=list(result.get('approvals',[]))
    gen1=list(result.get('gen1_approvals',[]))

    if checked:
        lines.append('I checked:')
        lines.extend(f'• {x}' for x in checked)

    if completed:
        lines.append('I completed:')
        lines.extend(f'• {x}' for x in completed)

    if approvals or gen1:
        lines.append('I need approval for:')
        lines.extend(
            f'• Gen-2 approval {x}'
            for x in approvals
        )
        lines.extend(
            f'• Gen-1 approval {x}'
            for x in gen1
        )

    if result.get('status') not in {'COMPLETED','CANCELLED'}:
        lines.extend([
            'Next:',
            '• resume verified remaining work when its gate is satisfied'
        ])

    if result.get('trace_id'):
        lines.append(f"Trace: {result['trace_id']}")

    lines.append(result['text'])
    return '\n'.join(lines)


def build_parser():
    p=argparse.ArgumentParser(prog='sparkle')

    p.add_argument('request',nargs='*')

    actions=p.add_mutually_exclusive_group()
    actions.add_argument('--resume')
    actions.add_argument('--approve')
    actions.add_argument('--reject')
    actions.add_argument('--cancel')

    p.add_argument('--session')
    p.add_argument('--json',action='store_true')
    p.add_argument('--verbose',action='store_true')

    return p


def entrypoint(argv=None):
    p=build_parser()
    a=p.parse_args(argv)

    store,agent,sessions=build_components(
        activate_external_connectors=True
    )

    if a.approve or a.reject:
        result=agent.decide_approval(
            a.approve or a.reject,
            'approve' if a.approve else 'reject'
        )
        text=(
            f"Approval {result['status'].lower()}: "
            f"{result['approval_id']}"
        )
        print(
            json.dumps(result,indent=2)
            if a.json
            else text
        )
        return 0

    if a.cancel:
        result=agent.cancel(a.cancel)
    elif a.resume:
        result=agent.resume(a.resume)
    else:
        request=normalize_request(a.request)
        if not request and sys.stdin.isatty():
            request=input('SPARKLE> ').strip()
        if not request:
            p.error(
                'provide a request, `chat` request, --resume, '
                '--cancel, --approve, or --reject'
            )
        result=agent.start(request)

    if a.session:
        try:
            sessions.attach_goal(
                a.session,
                result['goal_id']
            )
        except KeyError:
            s=sessions.create(result['goal_id'])
            if a.verbose:
                result['session_id']=s.session_id

    print(
        json.dumps(result,indent=2)
        if a.json
        else format_result(result,a.verbose)
    )

    closer=getattr(
        getattr(agent,'connectors',None),
        'close',
        None
    )
    if callable(closer):
        closer()

    return 0


if __name__=='__main__':
    entrypoint()