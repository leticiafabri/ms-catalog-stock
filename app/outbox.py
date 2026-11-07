import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime, timedelta, timezone

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from sqlalchemy import or_, select

from app.config import settings
from app.database import SessionLocal
from app.models import OutboxEvent

logger = logging.getLogger(__name__)


def claim_next_event() -> dict | None:
    """Claim one event briefly so only one replica publishes it at a time."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        event = session.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                or_(OutboxEvent.locked_until.is_(None), OutboxEvent.locked_until < now),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if event is None:
            return None

        event.attempts += 1
        event.locked_until = now + timedelta(seconds=30)
        claimed = {
            "id": event.id,
            "event_type": event.event_type,
            "payload": event.payload,
            "attempts": event.attempts,
        }
        session.commit()
        return claimed


def mark_published(event_id: str) -> None:
    with SessionLocal() as session:
        event = session.get(OutboxEvent, event_id)
        if event is not None:
            event.published_at = datetime.now(timezone.utc)
            event.locked_until = None
            event.last_error = None
            session.commit()


def release_after_failure(event_id: str, attempts: int, error: Exception) -> None:
    with SessionLocal() as session:
        event = session.get(OutboxEvent, event_id)
        if event is not None:
            delay_seconds = min(60, max(2, attempts * 2))
            event.locked_until = datetime.now(timezone.utc) + timedelta(
                seconds=delay_seconds
            )
            event.last_error = str(error)[:2000]
            session.commit()


async def publish_outbox_forever() -> None:
    """Publish durable outbox events; retry on broker and connection failures."""
    while True:
        connection = None
        try:
            connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            channel = await connection.channel(
                publisher_confirms=True, on_return_raises=True
            )
            exchange = await channel.declare_exchange(
                settings.rabbitmq_exchange,
                ExchangeType.TOPIC,
                durable=True,
            )
            logger.info("Connected to RabbitMQ exchange %s", settings.rabbitmq_exchange)

            while True:
                event = await asyncio.to_thread(claim_next_event)
                if event is None:
                    await asyncio.sleep(1)
                    continue

                try:
                    await connection.ready()
                    await exchange.publish(
                        Message(
                            body=json.dumps(event["payload"]).encode("utf-8"),
                            content_type="application/json",
                            delivery_mode=DeliveryMode.PERSISTENT,
                            message_id=event["id"],
                            type=event["event_type"],
                        ),
                        routing_key=event["event_type"],
                        mandatory=True,
                    )
                    await asyncio.to_thread(mark_published, event["id"])
                    logger.info(
                        "Published event %s (%s)", event["id"], event["event_type"]
                    )
                except Exception as exc:
                    logger.exception("Could not publish outbox event %s", event["id"])
                    await asyncio.to_thread(
                        release_after_failure,
                        event["id"],
                        event["attempts"],
                        exc,
                    )
                    if connection.is_closed:
                        raise
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("RabbitMQ publisher unavailable; retrying shortly")
            await asyncio.sleep(5)
        finally:
            if connection is not None and not connection.is_closed:
                with suppress(Exception):
                    await connection.close()
