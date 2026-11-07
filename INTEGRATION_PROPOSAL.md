# Proposta inicial de integração da equipe

Este documento registra uma proposta para o grupo discutir. Ela não altera a responsabilidade de cada integrante e pode ser ajustada quando os outros serviços estiverem prontos.

## Serviços e persistência

| Serviço | Responsabilidade | Linguagem | Banco exclusivo |
| --- | --- | --- | --- |
| A — Pedidos | Receber e acompanhar pedidos | C# | MySQL |
| B — Catálogo/Estoque | Consultar produtos, validar e reservar estoque | Python/FastAPI | PostgreSQL |
| C — Notificações | Consumir eventos e registrar notificações/histórico | Python | MongoDB |

Cada serviço acessa somente o próprio banco. A integração ocorre por HTTP/REST ou RabbitMQ, nunca por leitura direta das tabelas de outro serviço.

## Fluxo proposto

1. Cliente envia pedido para A.
2. A registra o pedido inicialmente como `PENDING` e chama B para reservar cada produto.
3. B valida e reserva o estoque atomicamente. O `POST` de reserva é a decisão autoritativa; uma consulta prévia de disponibilidade é apenas informativa e não garante que o estoque ainda estará livre.
4. Se B confirmar todas as reservas, A muda o pedido para `CONFIRMED`; se uma reserva falhar, A marca o pedido como `REJECTED`.
5. Para cada reserva confirmada, B persiste um evento na outbox, na mesma transação PostgreSQL da reserva, e o publica no RabbitMQ.
6. C consome o evento, registra a notificação/histórico no MongoDB e confirma a mensagem após persistir.

Se a equipe exigir cancelamento/liberação de estoque quando o pedido falhar depois de uma reserva parcial, B precisará de uma operação de cancelamento idempotente; essa compensação fica como decisão de integração antes de fechar o fluxo.

## Contrato REST B

Service DNS proposto: `http://ms-catalog-service:8080`.

Consultar disponibilidade (informativo):

```http
GET /api/catalog/products/{product_id}/availability?quantity={quantity}
```

```json
{
  "product_id": 12,
  "sku": "SKU-001",
  "requested_quantity": 2,
  "available_quantity": 8,
  "available": true
}
```

Reservar (valida e decrementa em uma operação):

```http
POST /api/catalog/products/{product_id}/reservations
Content-Type: application/json
```

```json
{
  "order_id": "identificador-do-pedido",
  "quantity": 2
}
```

Sucesso retorna `201 Created` e a reserva. Produto inexistente/inativo retorna `404`; estoque insuficiente ou conflito de quantidade para uma reserva repetida retorna `409`. Repetir a mesma reserva para o mesmo `order_id`, produto e quantidade é idempotente.

## Contrato RabbitMQ B → C

- Exchange: `app.events` (tipo `topic`, durável).
- Routing key: `catalog.stock.reserved`.
- Fila durável sugerida para C: `notifications.catalog-stock-reserved`.
- C vincula essa fila à routing key, persiste por `event_id` no MongoDB e só então confirma a entrega.
- O publicador pode reenviar após falha de confirmação; o consumidor precisa deduplicar por `event_id`.

O corpo da mensagem é documentado no README do Microsserviço B. A equipe deve confirmar se esse evento é suficiente para a notificação ou se C também precisa consumir `order.confirmed` publicado por A.

## Kubernetes, Service Discovery e Ingress

Proposta de Services no mesmo namespace Kubernetes:

- `ms-orders-service:8080` → API A.
- `ms-catalog-service:8080` → API B.
- `ms-notifications-service:8080` → API C (se C expuser API HTTP).
- `rabbitmq:5672` → broker compartilhado.
- `ms-orders-db-service`, `ms-catalog-db-service` e `ms-notifications-db-service` → bancos exclusivos de cada serviço.

O host do Ingress é único e as regras separam as APIs por caminho:

- `/api/orders` → A.
- `/api/catalog` → B.
- `/api/notifications` → C, se houver API externa.

Os endpoints de health ficam para probes internas do Kubernetes e não precisam de um caminho externo compartilhado. O Deployment B já está com três réplicas; a equipe pode mantê-lo como demonstração de escalabilidade horizontal.

## Etapas de implantação

1. Desenvolver e iniciar cada serviço localmente com Docker Compose.
2. Confirmar com o grupo contratos REST, eventos, status do pedido e compensação de reserva parcial.
3. Criar e publicar as imagens de cada serviço em um registry acessível ao cluster (por exemplo, Amazon ECR).
4. Usar um cluster EKS compartilhado ou criar um para a equipe; aplicar Secrets, bancos, RabbitMQ, Deployments, Services e Ingress no mesmo namespace.
5. Demonstrar no EKS o pedido integrado, a mensagem persistida em C, os bancos isolados, o Ingress e as respostas atendidas por Pods diferentes.

Antes de criar um EKS novo, verificar a estimativa de custo e se a equipe já tem uma conta/cluster AWS designado para a avaliação.
