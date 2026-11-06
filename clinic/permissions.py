from rest_framework.permissions import BasePermission


class IsClinicManagerOrReceptionist(BasePermission):
    """
    Allows access only to clinic managers, receptionists,
    and superusers.
    """

    def has_permission(self, request, view):
        # Get the user who sent the request
        user = request.user

        # Check whether the user is authenticated
        # and is either a superuser or belongs to an allowed group
        return (
            user.is_authenticated
            and (
                # Allow access to superusers
                user.is_superuser

                # Allow access to clinic managers and receptionists
                or user.groups.filter(
                    name__in=["ClinicManager", "Receptionist"]
                ).exists()
            )
        )