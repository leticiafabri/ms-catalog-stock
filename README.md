# MS Catalog Stock

Microsserviço B de Catálogo/Estoque em Python/FastAPI e PostgreSQL. Mantém seu catálogo e estoque, atende consultas REST do serviço de pedidos e registra reservas. Cada serviço mantém sua própria persistência; este serviço não acessa o MySQL do serviço A nem o MongoDB do serviço C.

## APIs

- `GET /health` — estado da API, conexão PostgreSQL e nome do Pod.
- `GET /instance` — identificador do Pod para demonstrar múltiplas réplicas.
- `POST /api/catalog/products` — cadastrar produto.
- `GET /api/catalog/products` — listar produtos.
- `GET /api/catalog/products/{id}` — consultar produto.
- `GET /api/catalog/products/{id}/availability?quantity=2` — verificar disponibilidade sem reservar.
- `POST /api/catalog/products/{id}/reservations` — reservar quantidade para um pedido.
- `GET /api/catalog/reservations/{order_id}` — consultar reservas de um pedido.

O Microsserviço A pode consultar disponibilidade por Service Discovery dentro do cluster:

    http://ms-catalog-service:8080/api/catalog/products/{id}/availability?quantity={quantidade}

As rotas, o identificador do produto e o payload REST devem ser alinhados com quem implementa o serviço A.

## Evento RabbitMQ

Quando uma reserva é confirmada, a API salva a reserva e o evento na mesma transação PostgreSQL. Um publicador em segundo plano envia eventos pendentes ao exchange tópico durável `app_events_exchange`, com a routing key `catalog.stock.reserved` e confirmação do broker. Se o RabbitMQ estiver indisponível, o evento fica na tabela outbox e será tentado novamente. Falhas de confirmação podem levar a uma nova entrega; consumidores devem deduplicar usando `event_id`.

Formato do corpo da mensagem:

```json
{
  "order_id": "identificador do pedido",
  "event_id": "uuid",
  "event_type": "catalog.stock.reserved",
  "timestamp": "data e hora ISO 8601",
  "payload": {
    "reservation_id": 1,
    "product_id": 1,
    "sku": "SKU-001",
    "quantity": 2,
    "remaining_quantity": 8
  }
}
```

O consumidor atual do Microsserviço C declara a fila durável `pedidos_events`, o exchange `app_events_exchange` e um binding que inclui `#`, portanto recebe a routing key `catalog.stock.reserved`. O corpo usa os campos de topo que o consumidor já lê (`order_id`, `event_id` e `event_type`) e `payload` como conteúdo do evento. Ao gravar no MongoDB, C deve deduplicar pelo `event_id`.

## Executar localmente

Na raiz do projeto:

    docker compose up --build

Documentação OpenAPI: `http://localhost:8080/docs`. O Compose inicia a API, seu PostgreSQL próprio e RabbitMQ local. O painel do RabbitMQ fica em `http://localhost:15672`; usuário e senha `catalog` são somente para desenvolvimento local.

Fluxo manual REST:

1. Criar produto em `POST /api/catalog/products` com SKU, nome, preço e quantidade.
2. Consultar `GET /api/catalog/products/{id}/availability?quantity=2`.
3. Reservar em `POST /api/catalog/products/{id}/reservations` com `order_id` e `quantity`.
4. Consultar novamente a disponibilidade e `GET /api/catalog/reservations/{order_id}`.
5. Confirmar no RabbitMQ que chegou uma mensagem com routing key `catalog.stock.reserved` na fila `pedidos_events` vinculada ao exchange `app_events_exchange`.

## Kubernetes / Amazon EKS

O RabbitMQ é compartilhado pela equipe e não é criado por estes manifests. O cluster deve oferecer um Service chamado `rabbitmq-service` no mesmo namespace, com credenciais de aplicação compartilhadas; ajustar o Secret `ms-catalog-runtime` em `k8s/02-app.yaml` conforme o broker implantado. Aplicar o banco, a aplicação e o Ingress:

    kubectl apply -f k8s/01-database.yaml
    kubectl rollout status deployment/ms-catalog-db
    kubectl apply -f k8s/02-app.yaml
    kubectl apply -f k8s/03-ingress.yaml

O Deployment B usa três réplicas. O Service ClusterIP chama-se `ms-catalog-service`; `/instance` ajuda a identificar qual Pod respondeu. As APIs externas passam pelo NGINX Ingress Controller no caminho `/api/catalog`. `/health` fica reservado às probes internas do Kubernetes para evitar colisão com outros serviços. Ver `INTEGRATION_PROPOSAL.md` para o contrato proposto com A e C.

Os valores de senha em `k8s/01-database.yaml` e `k8s/02-app.yaml` são exemplos. Substituí-los por Secrets do ambiente antes de implantar no EKS. `DATABASE_URL` aponta ao PostgreSQL exclusivo do B: `db` no Compose e `ms-catalog-db-service` no Kubernetes. O manifesto RabbitMQ atual do repositório C não cria usuário de aplicação; a equipe precisa criar credenciais próprias e compartilhá-las entre B e C. O RabbitMQ restringe o usuário padrão `guest` a conexões locais.

## Próximos alinhamentos da equipe

- A deve confirmar a chamada REST: identificador do produto, quantidade, resposta de disponibilidade e quando cria/reserva o pedido.
- C deve confirmar o consumo de `catalog.stock.reserved` na fila `pedidos_events`, o exchange `app_events_exchange` e a deduplicação por `event_id` no MongoDB.
- A equipe deve implantar o RabbitMQ uma vez no EKS, manter os bancos isolados por serviço e confirmar os Secrets e nomes DNS.
- Confirmar que B será a demonstração das três réplicas (já configuradas), o host compartilhado do Ingress e o processo de publicação da imagem Docker no registry usado pelo EKS.
