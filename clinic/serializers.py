from datetime import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers
from django.contrib.auth import get_user_model, password_validation
from django.db import transaction
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import Group

from .models import (
    Patient,
    Appointment,
    Service,
    normalize_digits,
    validate_national_code as check_national_code,
    validate_iranian_phone as check_iranian_phone,
)

# Get the currently configured User model
User = get_user_model()

class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = [
            "id",
            "first_name",
            "last_name",
            "national_code",
            "phone_number",
            "insurance_type",
            "sports_insurance",
        ]

    def validate_national_code(self, value):
        value = normalize_digits(value)

        try:
            check_national_code(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)

        return value

    def validate_phone_number(self, value):
        value = normalize_digits(value)

        try:
            check_iranian_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)

        return value


class PatientProfileSerializer(PatientSerializer):

    class Meta(PatientSerializer.Meta):
        # Prevent patients from modifying their ID and phone number
        read_only_fields = [
            "id",
            "phone_number",
        ]


class PatientRegistrationSerializer(PatientSerializer):

    # Accept the user's password without including it in the response
    password = serializers.CharField(
        write_only=True,
        validators=[password_validation.validate_password]
    )

    # Require the user to enter the password twice
    password_confirm = serializers.CharField(write_only=True)

    class Meta(PatientSerializer.Meta):
        fields = [
            "id",
            "first_name",
            "last_name",
            "national_code",
            "phone_number",
            "insurance_type",
            "sports_insurance",
            "password",
            "password_confirm",
        ]

        # Prevent clients from modifying the automatically generated ID
        read_only_fields = ["id"]

    def validate(self, attrs):

        # Check whether the password and its confirmation match
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({
                "password_confirm": "Password and confirmation do not match."
            })

        phone = attrs["phone_number"]

        # Prevent duplicate user accounts with the same phone number
        if User.objects.filter(username=phone).exists():
            raise serializers.ValidationError({
                "phone_number": "This phone number is already registered."
            })

        # Prevent users from claiming existing patient records
        if Patient.objects.filter(phone_number=phone).exists():
            raise serializers.ValidationError({
                "phone_number": (
                    "A patient record already exists for this phone number. "
                    "Please contact the receptionist."
                )
            })

        return attrs

    def create(self, validated_data):

        # Remove confirmation data because it is not stored in the database
        validated_data.pop("password_confirm")

        # Extract the password before creating the patient profile
        password = validated_data.pop("password")

        phone = validated_data["phone_number"]

        # Ensure that user and patient creation happen as one transaction
        with transaction.atomic():

            # Create the user account
            user = User.objects.create_user(
                username=phone,
                password=password
            )

            # Assign the Patient role
            patient_group = Group.objects.get(name="Patient")
            user.groups.add(patient_group)

            # Create the patient profile
            patient = Patient(
                user=user,
             **validated_data
            )

        # Validate and save the patient profile
        patient.full_clean()
        patient.save()

        return patient

class PhoneTokenObtainPairSerializer(TokenObtainPairSerializer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Remove the default username field
        self.fields.pop(User.USERNAME_FIELD, None)

        # Add the phone number field
        self.fields["phone_number"] = serializers.CharField(
            write_only=True
        )

    def validate(self, attrs):

        # Normalize the phone number
        phone = normalize_digits(attrs["phone_number"])

        # Authenticate using the phone number as the username
        return super().validate({
            User.USERNAME_FIELD: phone,
            "password": attrs["password"]
        })
    
    
class AppointmentSerializer(serializers.ModelSerializer):

    class Meta:
        # Specifies the model handled by this serializer.
        model = Appointment

        # Defines the fields included in the API.
        fields = [
            "id",
            "doctor",
            "schedule",
            "service",
            "appointment_date",
            "start_time",
            "end_time",
            "status",
            "created_at",
        ]

        # Prevents clients from modifying these fields through the API.
        read_only_fields = ["id", "status", "created_at"]

        # Makes doctor, schedule, and service mandatory input fields.
        extra_kwargs = {
            "doctor": {"required": True},
            "schedule": {"required": True},
            "service": {"required": True},
        }

    def validate(self, attrs):
        # Retrieves the current request from the serializer context.
        request = self.context.get("request")

        # Ensures that the user is authenticated before booking.
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError(
                "برای رزرو نوبت باید وارد حساب کاربری شوید."
            )

        # Retrieves the patient profile associated with the logged-in user.
        try:
            patient = request.user.patient_profile
        except Patient.DoesNotExist:
            raise serializers.ValidationError(
                "برای این حساب کاربری پرونده بیمار ثبت نشده است."
            )

        # Prevents booking appointments that start in the past.
        start_at = datetime.combine(
            attrs["appointment_date"],
            attrs["start_time"],
        )
        if start_at <= timezone.localtime().replace(tzinfo=None):
            raise serializers.ValidationError(
                {"appointment_date": "نمی‌توان برای زمان گذشته نوبت ثبت کرد."}
            )

        # Creates an appointment instance for model-level validation.
        appointment = Appointment(
            patient=patient,
            **attrs
        )

        # Runs the model's validation rules.
        try:
            appointment.full_clean()
        except DjangoValidationError as error:

            # Converts field-specific Django errors into DRF validation errors.
            if hasattr(error, "message_dict"):
                raise serializers.ValidationError(error.message_dict)

            # Handles validation errors that are not associated with specific fields.
            raise serializers.ValidationError(error.messages)

        # Adds the authenticated patient's profile to the validated data.
        attrs["patient"] = patient

        # Returns the validated data for the next serializer step.
        return attrs

    def create(self, validated_data):
        # Converts model validation errors into DRF errors during database creation.
        try:
            return super().create(validated_data)
        except DjangoValidationError as error:
            if hasattr(error, "message_dict"):
                raise serializers.ValidationError(error.message_dict)

            raise serializers.ValidationError(error.messages)
        
        
class ServiceSerializer(serializers.ModelSerializer):

    # Validates the service name
    def validate_service_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "نام خدمت نمی‌تواند خالی باشد."
            )

        return value

    # Validates the service duration
    def validate_duration_minutes(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "مدت زمان خدمت باید بیشتر از صفر باشد."
            )

        return value

    # Validates the service price
    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "قیمت خدمت نمی‌تواند منفی باشد."
            )

        return value

    # Validates the service description
    def validate_description(self, value):
        if value is not None and not value.strip():
            return None

        return value

    class Meta:
        model = Service

        fields = [
            "id",
            "service_name",
            "description",
            "duration_minutes",
            "price",
            "is_active",
        ]

        # The ID is generated automatically and cannot be modified
        read_only_fields = ["id"]