from rest_framework import generics, viewsets
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated, AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from django.shortcuts import get_object_or_404
from clinic.permissions import IsClinicManagerOrReceptionist

from .models import Patient, Service
from .serializers import (
    PatientSerializer,
    PatientProfileSerializer,
    PatientRegistrationSerializer,
    PhoneTokenObtainPairSerializer,
    AppointmentSerializer,
    ServiceSerializer,
)


# Provides API endpoints for listing and creating patients
class PatientListCreateAPIView(generics.ListCreateAPIView):
    queryset = Patient.objects.all()
    serializer_class = PatientSerializer

     # Only clinic managers, receptionists, and superusers can access this endpoint
    permission_classes = [IsClinicManagerOrReceptionist]


# Provides API endpoints for viewing and updating the patient's own profile
class PatientProfileView(generics.RetrieveUpdateAPIView):

    serializer_class = PatientProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        # Retrieve only the profile linked to the authenticated user
        return get_object_or_404(
            Patient,
            user=self.request.user
        )


# Provides an API endpoint for patient registration
class PatientRegistrationView(CreateAPIView):

    serializer_class = PatientRegistrationSerializer

    # Allow unauthenticated users to register
    permission_classes = [AllowAny]


# Provides an API endpoint for phone number authentication
class PhoneTokenObtainPairView(TokenObtainPairView):

    # Use the custom serializer for phone number login
    serializer_class = PhoneTokenObtainPairSerializer


# Provides an API endpoint for booking appointments
class AppointmentBookingView(CreateAPIView):
    serializer_class = AppointmentSerializer

    # Only authenticated users can book appointments
    permission_classes = [IsAuthenticated]


# Provides CRUD operations for managing services
class ServiceViewSet(viewsets.ModelViewSet):

    # Retrieves all services from the database
    queryset = Service.objects.all()

    # Defines the serializer used for data conversion and validation
    serializer_class = ServiceSerializer


