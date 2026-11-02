# myapp/migrations/XXXX_region_payments.py
#
# ⚠️ IMPORTANT:
# 1. Run: python manage.py makemigrations myapp --empty -n region_payments
# 2. Replace the generated file's content with this code.
# 3. Set `dependencies` to YOUR last migration name.
# 4. Run: python manage.py migrate myapp

from django.db import migrations, models


def set_binance_usdt_all(apps, schema_editor):
    """
    Binance + USDT are available in BOTH regions.
    Any existing JAZZCASH / EASYPAISA rows stay PK (default).
    """
    SystemPaymentMethod = apps.get_model("myapp", "SystemPaymentMethod")
    SystemPaymentMethod.objects.filter(
        method_type__in=["BINANCE", "USDT"]
    ).update(country="ALL")


def reverse_binance_usdt(apps, schema_editor):
    SystemPaymentMethod = apps.get_model("myapp", "SystemPaymentMethod")
    SystemPaymentMethod.objects.filter(country="ALL").update(country="PK")


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0028_alter_depositrequest_options_and_more"),
    ]

    operations = [
        # ---- UserProfileBalance.country ----
        migrations.AddField(
            model_name="userprofilebalance",
            name="country",
            field=models.CharField(
                blank=True,
                choices=[("PK", "Pakistan"), ("IN", "India")],
                db_index=True,
                help_text="Region locked after signup. PK or IN.",
                max_length=2,
                null=True,
            ),
        ),

        # ---- SystemPaymentMethod.country ----
        migrations.AddField(
            model_name="systempaymentmethod",
            name="country",
            field=models.CharField(
                choices=[
                    ("PK", "Pakistan"),
                    ("IN", "India"),
                    ("ALL", "All Regions"),
                ],
                db_index=True,
                default="ALL",
                help_text="Which region can see this method.",
                max_length=3,
            ),
        ),

        # ---- METHOD_CHOICES updated (metadata only) ----
        migrations.AlterField(
            model_name="systempaymentmethod",
            name="method_type",
            field=models.CharField(
                choices=[
                    ("JAZZCASH", "JazzCash"),
                    ("EASYPAISA", "EasyPaisa"),
                    ("BINANCE", "Binance"),
                    ("USDT", "USDT"),
                    ("RAZORPAY", "Razorpay"),
                    ("PHONEPE", "PhonePe"),
                ],
                max_length=20,
                unique=True,
            ),
        ),

        migrations.AlterField(
            model_name="withdrawalrequest",
            name="method",
            field=models.CharField(
                choices=[
                    ("JAZZCASH", "JazzCash"),
                    ("EASYPAISA", "EasyPaisa"),
                    ("BINANCE", "Binance"),
                    ("USDT", "USDT"),
                    ("RAZORPAY", "Razorpay"),
                    ("PHONEPE", "PhonePe"),
                ],
                max_length=20,
            ),
        ),

        # ---- Data migration: BINANCE + USDT → ALL ----
        migrations.RunPython(set_binance_usdt_all, reverse_binance_usdt),
    ]