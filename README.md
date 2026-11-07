# MS Catalog Stock

Microsserviço B de Catálogo/Estoque. Responsabilidade: manter seu próprio catálogo e quantidade disponível, responder à consulta síncrona de disponibilidade feita pelo serviço de pedidos e registrar reservas de estoque.

## Contrato inicial

- GET /health — estado da API, conexão PostgreSQL e nome do Pod.
- GET /instance — identificador do Pod para demonstrar múltiplas réplicas.
- POST /api/catalog/products — cadastrar produto.
- GET /api/catalog/products — listar produtos.
- GET /api/catalog/products/{id} — consultar produto.
- GET /api/catalog/products/{id}/availability?quantity=2 — verificar disponibilidade sem reservar.
- POST /api/catalog/products/{id}/reservations — reservar quantidade para um pedido.
- GET /api/catalog/reservations/{order_id} — consultar reservas de um pedido.

O serviço de pedidos pode consultar a disponibilidade por Service Discovery:

    http://ms-catalog-service:8080/api/catalog/products/{id}/availability?quantity={quantidade}

Quando a equipe alinhar o contrato, revisar rota, formato de identificador, payload de evento e códigos HTTP com o integrante responsável pelo serviço A.

## Executar localmente

Na pasta ms-catalog-stock, criar um ambiente com Docker Compose:

    docker compose up --build

Documentação OpenAPI:

    http://localhost:8080/docs

O Compose sobe somente a API B e seu PostgreSQL próprio. RabbitMQ pertence ao fluxo assíncrono da equipe; este serviço não publica nem consome mensagens no contrato inicial.

## Teste manual do fluxo REST

1. Criar produto em POST /api/catalog/products com SKU, nome, preço e quantidade.
2. Consultar GET /api/catalog/products/{id}/availability?quantity=2.
3. Reservar com POST /api/catalog/products/{id}/reservations usando order_id e quantity.
4. Consultar novamente disponibilidade e GET /api/catalog/reservations/{order_id}.

## Kubernetes

Os manifests estão em k8s. Aplicar o banco antes da aplicação:

    kubectl apply -f k8s/01-database.yaml
    kubectl rollout status deployment/ms-catalog-db
    kubectl apply -f k8s/02-app.yaml
    kubectl apply -f k8s/03-ingress.yaml

O Deployment da API inicia com três réplicas para facilitar a demonstração de escalabilidade e balanceamento. Os Pods compartilham somente o banco deste serviço. O hostname retornado em /health e /instance permite observar qual réplica atendeu.

## Configuração

DATABASE_URL aponta ao banco PostgreSQL exclusivo deste serviço. Em Docker Compose, o host é db; no Kubernetes, ms-catalog-db-service. Os valores simples de desenvolvimento nos manifests precisam ser substituídos por Secret próprio do ambiente antes do deploy compartilhado.

## Decisões ainda a alinhar com a equipe

- Confirmar linguagem e banco para garantir que a equipe atenda diversidade tecnológica.
- Confirmar rota e payload REST com o Microsserviço A.
- Confirmar se B também reserva estoque durante criação do pedido ou apenas valida disponibilidade.
- Confirmar qual serviço será usado para demonstrar três réplicas; o manifesto atual deixa B com três.
- Definir domínio e acesso do Ingress compartilhado, evitando conflito de caminhos.
