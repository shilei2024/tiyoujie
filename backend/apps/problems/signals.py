from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Asset, StoredObject


@receiver(post_delete, sender=Asset)
def schedule_object_cleanup(sender, instance, **kwargs):
    StoredObject.objects.filter(pk=instance.object_id).update(state="purge_pending")
