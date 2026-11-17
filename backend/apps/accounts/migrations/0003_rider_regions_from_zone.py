"""005 (research R10): copy each rider's free-text zone into regions when it names a delivery region."""

from django.db import migrations


def zone_to_regions(apps, schema_editor):
    RiderProfile = apps.get_model("accounts", "RiderProfile")
    DeliveryRegion = apps.get_model("orders", "DeliveryRegion")
    for profile in RiderProfile.objects.exclude(zone=""):
        region = DeliveryRegion.objects.filter(name__iexact=profile.zone.strip()).first()
        if region is not None:
            profile.regions.add(region)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_riderprofile_regions"),
        ("orders", "__first__"),
    ]

    operations = [migrations.RunPython(zone_to_regions, migrations.RunPython.noop)]
