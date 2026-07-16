from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.customer import Customer, Establishment
from app.models.device import Device
from app.models.knowledge import KnowledgeDocument
from app.models.messaging import Contact
from app.models.product import Product, ProductVersion
from app.models.tenant import Tenant
from app.models.ticket import Ticket, TicketPriority, TicketStatus
from app.models.user import Permission, Role, RolePermission, User, UserRole
from app.security.passwords import hash_password
from app.services.knowledge.documents import create_document
from app.services.protocols import generate_ticket_protocol

PERMISSIONS = [
    ("tickets:view", "Visualizar chamados"),
    ("tickets:update", "Atualizar chamados"),
    ("customers:manage", "Gerenciar clientes"),
    ("products:manage", "Gerenciar produtos"),
    ("users:manage", "Gerenciar usuarios"),
    ("audit:view", "Visualizar auditoria"),
]

DEMO_KNOWLEDGE_DOCS = [
    ("PDV nao abre", "PDV PowerVarejo", "pdv", "Quando o PDV nao abre, coletar mensagem de erro, confirmar se ocorre em um ou todos os caixas e verificar se o servidor responde. Acoes seguras: reiniciar aplicativo e pedir captura de tela."),
    ("Todos os caixas sem conexao", "PDV PowerVarejo", "conectividade", "Todos os caixas sem conexao indica possivel parada de servidor, rede ou servico central. Classificar como P1 quando loja nao vende. Encaminhar tecnico humano e perguntar se o servidor esta ligado."),
    ("Impressora termica nao imprime", "PDV PowerVarejo", "impressao", "Para impressora termica que nao imprime, confirmar impressora padrao, cabos, energia e fila de impressao. Nao executar scripts. Coletar se ocorre em um caixa ou em todos."),
    ("NFC-e rejeitada", "Emissor NFC-e", "fiscal", "NFC-e rejeitada exige coletar codigo de rejeicao, serie, ambiente e mensagem completa. Risco fiscal pode elevar prioridade. Nao alterar regras fiscais automaticamente."),
    ("TEF indisponivel", "TEF", "pagamentos", "TEF indisponivel pode envolver internet, pinpad ou autorizadora. Confirmar se cartoes param em todos os caixas e coletar mensagem exibida."),
    ("Servico do banco parado", "Retaguarda PowerVarejo", "banco", "Servico do banco parado pode parar a loja e envolver risco de dados. Encaminhar tecnico humano. Nao executar SQL nem alterar banco automaticamente."),
    ("Erro de conexao com servidor", "Retaguarda PowerVarejo", "conectividade", "Erro de conexao com servidor requer confirmar rede, servidor ligado e impacto. Se todos os terminais falham, classificar como P1."),
    ("Certificado digital nao encontrado", "Emissor NFC-e", "certificado", "Certificado digital nao encontrado exige confirmar validade e mensagem no sistema. Nao trocar certificado nem alterar configuracao fiscal sem autorizacao."),
]


def get_or_create(db, model, defaults: dict | None = None, **lookup):
    instance = db.scalar(select(model).filter_by(**lookup))
    if instance is not None:
        return instance
    data = {**lookup, **(defaults or {})}
    instance = model(**data)
    db.add(instance)
    db.flush()
    return instance


def seed_development() -> None:
    settings = get_settings()
    if settings.app_env != "development" or not settings.seed_demo_data:
        raise RuntimeError("Development seed is disabled outside APP_ENV=development with SEED_DEMO_DATA=true.")
    if not settings.demo_admin_password:
        raise RuntimeError("DEMO_ADMIN_PASSWORD must be set to seed the administrator user.")
    try:
        admin_password_hash = hash_password(settings.demo_admin_password)
    except ValueError as exc:
        raise RuntimeError(f"Invalid DEMO_ADMIN_PASSWORD for development seed: {exc}") from exc

    with SessionLocal() as db:
        tenant = get_or_create(
            db,
            Tenant,
            slug="powertec",
            defaults={"name": "PowerTec Assistencia Tecnica", "city": "Parauapebas", "state": "Para"},
        )
        role = get_or_create(db, Role, tenant_id=tenant.id, name="administrador", defaults={"description": "Administrador"})

        permission_rows = []
        for code, description in PERMISSIONS:
            permission_rows.append(get_or_create(db, Permission, code=code, defaults={"description": description}))
        db.flush()
        for permission in permission_rows:
            get_or_create(db, RolePermission, role_id=role.id, permission_id=permission.id)

        admin = get_or_create(
            db,
            User,
            tenant_id=tenant.id,
            email="admin@powertec.local",
            defaults={
                "full_name": "Administrador PowerTec",
                "hashed_password": admin_password_hash,
                "is_active": True,
            },
        )
        get_or_create(db, UserRole, user_id=admin.id, role_id=role.id)

        customer = get_or_create(
            db,
            Customer,
            tenant_id=tenant.id,
            name="Supermercado Modelo",
            defaults={
                "document": "00.000.000/0000-00 DEMO",
                "city": "Parauapebas",
                "phone": "+5594999990000",
                "system_name": "PowerVarejo",
                "is_active": True,
            },
        )
        establishment = get_or_create(
            db,
            Establishment,
            tenant_id=tenant.id,
            customer_id=customer.id,
            name="Loja Matriz",
            defaults={"internal_code": "LOJA-001", "city": "Parauapebas", "phone": "+5594999990001"},
        )
        get_or_create(
            db,
            Contact,
            tenant_id=tenant.id,
            phone="+5594999990001",
            defaults={
                "customer_id": customer.id,
                "name": "Joao da Silva",
                "is_temporary": False,
                "validation_status": "validated",
                "created_at": datetime.now(UTC),
            },
        )
        get_or_create(
            db,
            Contact,
            tenant_id=tenant.id,
            phone="+5594999990002",
            defaults={
                "name": None,
                "is_temporary": True,
                "validation_status": "pending",
                "created_at": datetime.now(UTC),
            },
        )
        for name, device_type in [("SERVIDOR-01", "server"), ("CAIXA-01", "pos"), ("CAIXA-02", "pos")]:
            get_or_create(
                db,
                Device,
                tenant_id=tenant.id,
                customer_id=customer.id,
                establishment_id=establishment.id,
                name=name,
                defaults={"device_type": device_type},
            )
        products = []
        for name in ["PDV PowerVarejo", "Retaguarda PowerVarejo", "Emissor NFC-e"]:
            product = get_or_create(db, Product, tenant_id=tenant.id, name=name, defaults={"description": "Produto demo"})
            get_or_create(db, ProductVersion, tenant_id=tenant.id, product_id=product.id, version="demo-1.0")
            products.append(product)

        ticket_descriptions = [
            ("PDV nao inicia", TicketPriority.P1.value, products[0].id),
            ("Impressora termica nao imprime", TicketPriority.P3.value, products[0].id),
            ("Erro de conexao com o servidor", TicketPriority.P2.value, products[1].id),
            ("NFC-e rejeitada", TicketPriority.P1.value, products[2].id),
            ("Servico do banco de dados parado", TicketPriority.P1.value, products[1].id),
        ]
        for description, priority, product_id in ticket_descriptions:
            exists = db.scalar(select(Ticket).where(Ticket.tenant_id == tenant.id, Ticket.description == description))
            if exists is None:
                db.add(
                    Ticket(
                        tenant_id=tenant.id,
                        protocol=generate_ticket_protocol(),
                        customer_id=customer.id,
                        establishment_id=establishment.id,
                        product_id=product_id,
                        priority=priority,
                        status=TicketStatus.NEW.value,
                        description=description,
                        ai_summary="Chamado ficticio criado pelo seed de desenvolvimento.",
                        opened_at=datetime.now(UTC),
                    )
                )
        for title, product_name, category, body in DEMO_KNOWLEDGE_DOCS:
            exists = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == tenant.id, KnowledgeDocument.title == title))
            if exists is None:
                create_document(
                    db,
                    tenant.id,
                    admin.id,
                    title=title,
                    filename=f"{title.lower().replace(' ', '-')}.md",
                    mime_type="text/markdown",
                    content=f"# {title}\n\n{body}\n".encode("utf-8"),
                    description="Documento ficticio de demonstracao da Etapa 3.",
                    category=category,
                    product=product_name,
                    version="demo-1.0",
                    manufacturer="PowerTec Demo",
                    approve=True,
                )
        db.commit()
        print("Development seed completed for tenant 'powertec' and user 'admin@powertec.local'.")


if __name__ == "__main__":
    seed_development()
