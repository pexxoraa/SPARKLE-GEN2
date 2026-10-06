"""SPARKLE dependency composition. Keep wiring here, not in business logic.

The rest of the application receives already-built services and never knows how
the runtime is assembled.
"""

from __future__ import annotations
import os
from pathlib import Path
from .agents.personal import PersonalAgent
from .connector_catalog import build_default_connectors
from .application.context_sources import PersonalContextAssembler
from .devices import DeviceManager
from .gen1 import LocalGen1Gateway
from .sessions import SessionService
from .personal_data import PersonalDataOrchestrator
from .world_model import WorldModel
from .policy import PolicyEngine
from .infrastructure.storage import Gen2Store
from .environment_gateway import load_environment_gateway
from .document_intelligence import DocumentIntelligenceService
from .image_runtime import ImageGenerationService
from .application.learning_orchestration import LearningOrchestrator
from .daily_os import DailyOperatingSystemService
from .notifications import NotificationIntelligenceService,NotificationCenter
from .notification_delivery import NotificationDeliveryOrchestrator
from .dashboard import PersonalOperationsService
from .diagnostics import SelfDiagnostics
from .perception import PerceptionService,ROS2PosePerceptionAdapter
from .application.retrieval import CapabilityRoutedEmbedder,CapabilityRoutedReranker,PersistentSemanticIndex
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



