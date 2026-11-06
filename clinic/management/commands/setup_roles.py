
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.apps import apps


# Define the permissions assigned to each user role
ROLE_PERMISSIONS = {
    "ClinicManager": {
        "patient": ["view", "add", "change"],
        "doctor": ["view", "add", "change"],
        "service": ["view", "add", "change"],
        "doctorschedule": ["view", "add", "change"],
        "appointment": ["view", "add", "change"],
        "physiotherapysession": ["view", "add", "change"],
        "notification": ["view", "add", "change"],
        "auditlog": ["view"],
        "inventoryitem": ["view", "add", "change"],
        "inventorytransaction": ["view", "add"],
    },

    "Receptionist": {
        "patient": ["view", "add", "change"],
        "appointment": ["view", "add", "change"],
        "doctor": ["view"],
        "doctorschedule": ["view"],
        "service": ["view"],
        "notification": ["view"],
    },

    "InventoryManager": {
        "inventoryitem": ["view", "add", "change"],
        "inventorytransaction": ["view", "add"],
    },

    "Doctor": {
        "patient": ["view"],
        "appointment": ["view"],
        "doctorschedule": ["view"],
        "service": ["view"],
        "physiotherapysession": ["view", "add", "change"],
    },

    "Patient": {},
}


class Command(BaseCommand):

    # Define the command description shown in the help output
    help = "Create clinic role groups and assign permissions"

    def handle(self, *args, **options):

        # Iterate through all defined roles and their permissions
        for role_name, model_permissions in ROLE_PERMISSIONS.items():

            # Get the group if it exists; otherwise, create it
            group, created = Group.objects.get_or_create(
                name=role_name
            )

            permissions = []

            # Iterate through each model and its allowed actions
            for model_name, actions in model_permissions.items():

                # Get the model class from the clinic application
                model = apps.get_model("clinic", model_name)

                # Get the ContentType associated with the model
                content_type = ContentType.objects.get_for_model(model)

                # Find each permission using its codename
                for action in actions:

                    codename = f"{action}_{model_name}"

                    try:
                        permission = Permission.objects.get(
                            content_type=content_type,
                            codename=codename,
                        )

                    # Stop execution if the required permission does not exist
                    except Permission.DoesNotExist:
                        raise CommandError(
                            f"Permission '{codename}' does not exist. "
                            "Run migrations first."
                        )

                    permissions.append(permission)

            # Replace the group's current permissions with the defined permissions
            group.permissions.set(permissions)

            # Display whether the group was created or updated
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created group: {role_name}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Updated group: {role_name}"
                    )
                )

        # Display a success message after configuring all roles
        self.stdout.write(
            self.style.SUCCESS(
                "All clinic roles and permissions were configured."
            )
        )
