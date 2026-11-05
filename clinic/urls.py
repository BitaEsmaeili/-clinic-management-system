
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    PatientListCreateAPIView,
    PatientProfileView,
    PatientRegistrationView,
    PhoneTokenObtainPairView,
    AppointmentBookingView,
    ServiceViewSet,
)

# Creates a router for ViewSet-based API endpoints
router = DefaultRouter()

# Registers the Service API routes
router.register(r"services", ServiceViewSet, basename="service")


urlpatterns = [
    # Patient API: List and create patients
    path(
        "patients/",
        PatientListCreateAPIView.as_view(),
        name="patient-list-create",
    ),

    # Patient API: View and update the authenticated patient's profile
    path(
        "patients/me/",
        PatientProfileView.as_view(),
        name="patient-profile",
    ),  

    # Register a new patient account
    path(
        "auth/register/",
        PatientRegistrationView.as_view(),
        name="patient-register",
    ),

    # Obtain access and refresh tokens using phone number and password
    path(
        "auth/token/",
        PhoneTokenObtainPairView.as_view(),
        name="token-obtain-pair",
    ),

    # Obtain a new access token using a refresh token
    path(
        "auth/token/refresh/",
        TokenRefreshView.as_view(),
        name="token-refresh",
    ),

    # Appointment API: Book an appointment
    path(
        "appointments/book/",
        AppointmentBookingView.as_view(),
        name="appointment-book",
    ),

    # Includes automatically generated Service API routes
    path("", include(router.urls)),

        # Authentication API endpoints


]
