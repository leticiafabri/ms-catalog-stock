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

Quando uma reserva é confirmada, a API salva a reserva e o evento na mesma transação PostgreSQL. Um publicador em segundo plano envia eventos pendentes ao exchange tópico durável `app.events`, com a routing key `catalog.stock.reserved` e confirmação do broker. Se o RabbitMQ estiver indisponível, o evento fica na tabela outbox e será tentado novamente. Falhas de confirmação podem levar a uma nova entrega; consumidores devem deduplicar usando `event_id`.

Formato do corpo da mensagem:

```json
{
  "event_id": "uuid",
  "event_type": "catalog.stock.reserved",
  "occurred_at": "data e hora ISO 8601",
  "data": {
    "reservation_id": 1,
    "order_id": "identificador do pedido",
    "product_id": 1,
    "sku": "SKU-001",
    "quantity": 2,
    "remaining_quantity": 8
  }
}
```

O Microsserviço C deve declarar uma fila durável e vinculá-la ao exchange `app.events` com a routing key `catalog.stock.reserved`. Ao gravar o evento no MongoDB, pode usar `event_id` como chave de idempotência. Confirmar esse contrato e os nomes de exchange/fila com quem implementa C.

## Executar localmente

Na raiz do projeto:

    docker compose up --build

Documentação OpenAPI: `http://localhost:8080/docs`. O Compose inicia a API, seu PostgreSQL próprio e RabbitMQ local. O painel do RabbitMQ fica em `http://localhost:15672`; usuário e senha `catalog` são somente para desenvolvimento local.

Fluxo manual REST:

1. Criar produto em `POST /api/catalog/products` com SKU, nome, preço e quantidade.
2. Consultar `GET /api/catalog/products/{id}/availability?quantity=2`.
3. Reservar em `POST /api/catalog/products/{id}/reservations` com `order_id` e `quantity`.
4. Consultar novamente a disponibilidade e `GET /api/catalog/reservations/{order_id}`.
5. Confirmar no RabbitMQ que chegou uma mensagem com routing key `catalog.stock.reserved` depois que houver uma fila vinculada ao exchange `app.events`.

## Kubernetes / Amazon EKS

O RabbitMQ é compartilhado pela equipe e não é criado por estes manifests. O cluster deve oferecer um Service chamado `rabbitmq` no mesmo namespace, com credenciais compatíveis com `RABBITMQ_URL`; se nomes ou credenciais forem diferentes, ajustar o Secret `ms-catalog-runtime` em `k8s/02-app.yaml`. Aplicar o banco, a aplicação e o Ingress:

    kubectl apply -f k8s/01-database.yaml
    kubectl rollout status deployment/ms-catalog-db
    kubectl apply -f k8s/02-app.yaml
    kubectl apply -f k8s/03-ingress.yaml

O Deployment B usa três réplicas. O Service ClusterIP chama-se `ms-catalog-service`; `/instance` ajuda a identificar qual Pod respondeu. As APIs externas passam pelo NGINX Ingress Controller. O Ingress deste serviço usa os caminhos `/api/catalog` e `/health`; combinar host e caminhos com o restante da equipe.

Os valores de senha em `k8s/01-database.yaml` e `k8s/02-app.yaml` são exemplos. Substituí-los por Secrets do ambiente antes de implantar no EKS. `DATABASE_URL` aponta ao PostgreSQL exclusivo do B: `db` no Compose e `ms-catalog-db-service` no Kubernetes.

## Próximos alinhamentos da equipe

- A deve confirmar a chamada REST: identificador do produto, quantidade, resposta de disponibilidade e quando cria/reserva o pedido.
- C deve confirmar o consumo de `catalog.stock.reserved`, a fila durável, o exchange compartilhado e a deduplicação por `event_id` no MongoDB.
- A equipe deve implantar o RabbitMQ uma vez no EKS, manter os bancos isolados por serviço e confirmar os Secrets e nomes DNS.
- Confirmar que B será a demonstração das três réplicas (já configuradas), o host compartilhado do Ingress e o processo de publicação da imagem Docker no registry usado pelo EKS.
