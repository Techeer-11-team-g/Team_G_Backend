"""
RabbitMQ client for direct message publishing/consuming.
"""

import json
import pika
from django.conf import settings


class RabbitMQClient:
    """RabbitMQ client for pub/sub messaging."""

    def __init__(self):
        self.connection = None
        self.channel = None

    def connect(self):
        """Establish connection to RabbitMQ."""
        credentials = pika.PlainCredentials(
            username=settings.CELERY_BROKER_URL.split('://')[1].split(':')[0] if '://' in settings.CELERY_BROKER_URL else 'guest',
            password='guest'
        )

        # Parse from environment or use defaults
        import os
        host = os.getenv('RABBITMQ_HOST', 'localhost')
        port = int(os.getenv('RABBITMQ_PORT', 5672))
        user = os.getenv('RABBITMQ_USER', 'guest')
        password = os.getenv('RABBITMQ_PASSWORD', 'guest')

        credentials = pika.PlainCredentials(user, password)
        parameters = pika.ConnectionParameters(
            host=host,
            port=port,
            credentials=credentials,
        )

        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()
        return self

    def close(self):
        """Close connection."""
        if self.connection and not self.connection.is_closed:
            self.connection.close()

    def declare_queue(self, queue_name: str, durable: bool = True):
        """Declare a queue."""
        self.channel.queue_declare(queue=queue_name, durable=durable)

    def publish(self, queue_name: str, message: dict):
        """
        Publish a message to a queue.

        Args:
            queue_name: Target queue name
            message: Message dict (will be JSON serialized)
        """
        self.declare_queue(queue_name)
        self.channel.basic_publish(
            exchange='',
            routing_key=queue_name,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Persistent
                content_type='application/json',
            )
        )

    def consume(self, queue_name: str, callback, auto_ack: bool = False):
        """
        Start consuming messages from a queue.

        Args:
            queue_name: Queue to consume from
            callback: Function(channel, method, properties, body)
            auto_ack: Auto acknowledge messages
        """
        self.declare_queue(queue_name)
        self.channel.basic_consume(
            queue=queue_name,
            on_message_callback=callback,
            auto_ack=auto_ack,
        )
        self.channel.start_consuming()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 사용 예시
def example_publisher():
    """메시지 발행 예시"""
    with RabbitMQClient() as client:
        client.publish('notifications', {
            'type': 'user_signup',
            'user_id': 123,
            'email': 'user@example.com'
        })


def example_consumer():
    """메시지 구독 예시"""
    def callback(ch, method, properties, body):
        message = json.loads(body)
        print(f"Received: {message}")
        # 처리 완료 후 ACK
        ch.basic_ack(delivery_tag=method.delivery_tag)


def get_rabbitmq_client():
    """RabbitMQ client singleton or factory."""
    return RabbitMQClient()

