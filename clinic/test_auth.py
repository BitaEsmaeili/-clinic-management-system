
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Patient,
    Doctor,
    DoctorSchedule,
    Service,
)


User = get_user_model()


class PatientRegistrationTests(APITestCase):

    def setUp(self):
        self.url = reverse("patient-register")

        self.valid_data = {
            "first_name": "Ali",
            "last_name": "Ahmadi",
            "phone_number": "09123456789",
            "national_code": "",
            "insurance_type": "None",
            "sports_insurance": False,
            "password": "Violet!River92Stone",
            "password_confirm": "Violet!River92Stone",
        }

    def test_successful_registration(self):
        response = self.client.post(
            self.url,
            self.valid_data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(username="09123456789")
        patient = Patient.objects.get(phone_number="09123456789")

        self.assertEqual(patient.user, user)
        self.assertTrue(user.check_password("Violet!River92Stone"))

        self.assertNotIn("password", response.data)
        self.assertNotIn("password_confirm", response.data)

    def test_duplicate_user_phone_number(self):
        User.objects.create_user(
            username="09123456789",
            password="Another!SecurePassword92"
        )

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone_number", response.data)

    def test_existing_patient_record(self):
        Patient.objects.create(
            first_name="Reza",
            last_name="Ahmadi",
            phone_number="09123456789"
        )

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone_number", response.data)

    def test_password_confirmation_mismatch(self):
        data = self.valid_data.copy()
        data["password_confirm"] = "Different!Password92"

        response = self.client.post(
            self.url,
            data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password_confirm", response.data)

    def test_weak_password(self):
        data = self.valid_data.copy()
        data["password"] = "123"
        data["password_confirm"] = "123"

        response = self.client.post(
            self.url,
            data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    def test_invalid_phone_number(self):
        data = self.valid_data.copy()
        data["phone_number"] = "123456"

        response = self.client.post(
            self.url,
            data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone_number", response.data)

    def test_invalid_national_code(self):
        data = self.valid_data.copy()
        data["national_code"] = "1234567890"

        response = self.client.post(
            self.url,
            data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("national_code", response.data)

    def test_registration_with_persian_digits(self):
        data = self.valid_data.copy()
        data["phone_number"] = "۰۹۱۲۳۴۵۶۷۸۹"

        response = self.client.post(
            self.url,
            data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertTrue(
            User.objects.filter(username="09123456789").exists()
        )


class PhoneLoginTests(APITestCase):

    def setUp(self):
        self.url = reverse("token-obtain-pair")

        self.phone = "09123456789"
        self.password = "Violet!River92Stone"

        self.user = User.objects.create_user(
            username=self.phone,
            password=self.password
        )

    def test_successful_login(self):
        response = self.client.post(
            self.url,
            {
                "phone_number": self.phone,
                "password": self.password,
            },
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_with_wrong_password(self):
        response = self.client.post(
            self.url,
            {
                "phone_number": self.phone,
                "password": "Wrong!Password123",
            },
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_with_unregistered_phone(self):
        response = self.client.post(
            self.url,
            {
                "phone_number": "09111111111",
                "password": self.password,
            },
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_with_persian_phone_digits(self):
        response = self.client.post(
            self.url,
            {
                "phone_number": "۰۹۱۲۳۴۵۶۷۸۹",
                "password": self.password,
            },
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TokenRefreshTests(APITestCase):

    def setUp(self):
        self.url = reverse("token-refresh")

        self.user = User.objects.create_user(
            username="09123456789",
            password="Violet!River92Stone"
        )

        self.refresh = RefreshToken.for_user(self.user)

    def test_successful_token_refresh(self):
        response = self.client.post(
            self.url,
            {"refresh": str(self.refresh)},
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_invalid_refresh_token(self):
        response = self.client.post(
            self.url,
            {"refresh": "invalid-token"},
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AppointmentAuthenticationTests(APITestCase):

    def setUp(self):
        self.url = reverse("appointment-book")

        self.doctor = Doctor.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            specialty="Physiotherapy",
            is_active=True,
            appointment_duration=30
        )

        self.service = Service.objects.create(
            service_name="Physiotherapy Test",
            duration_minutes=30,
            price=100000,
            is_active=True
        )

        self.appointment_date = timezone.localdate() + timedelta(days=2)

        self.schedule = DoctorSchedule.objects.create(
            doctor=self.doctor,
            schedule_date=self.appointment_date,
            start_time=time(9, 0),
            end_time=time(12, 0)
        )

        self.appointment_data = {
            "doctor": self.doctor.pk,
            "schedule": self.schedule.pk,
            "service": self.service.pk,
            "appointment_date": self.appointment_date.isoformat(),
            "start_time": "10:00:00",
            "end_time": "10:30:00",
        }

    def test_appointment_without_authentication(self):
        response = self.client.post(
            self.url,
            self.appointment_data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_user_without_patient_profile(self):
        user = User.objects.create_user(
            username="09123456789",
            password="Violet!River92Stone"
        )

        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        response = self.client.post(
            self.url,
            self.appointment_data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)

    def test_authenticated_patient_can_book_appointment(self):
        user = User.objects.create_user(
            username="09123456789",
            password="Violet!River92Stone"
        )

        Patient.objects.create(
            user=user,
            first_name="Ali",
            last_name="Ahmadi",
            phone_number="09123456789"
        )

        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

        response = self.client.post(
            self.url,
            self.appointment_data,
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
