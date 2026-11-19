from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('epilepscreen', '0005_inr_prices_and_customer_spend')]
    operations = [migrations.RunSQL('ALTER TABLE epilepsy ADD COLUMN upload_owner VARCHAR(64) NULL', 'ALTER TABLE epilepsy DROP COLUMN upload_owner', state_operations=[migrations.AddField(model_name='videorecord', name='upload_owner', field=models.CharField(max_length=64, null=True, editable=False))])]
