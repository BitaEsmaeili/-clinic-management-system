
import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.contrib.auth.models import User


# تبدیل ارقام فارسی و عربی به ارقام انگلیسی
def normalize_digits(value):
    translation = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )
    return value.translate(translation) if value else value


# اعتبارسنجی کد ملی ایران
def validate_national_code(value):
    if not value:
        return

    value = normalize_digits(value)

    if not re.fullmatch(r"\d{10}", value):
        raise ValidationError("کد ملی باید دقیقاً ۱۰ رقم باشد.")

    if len(set(value)) == 1:
        raise ValidationError("کد ملی واردشده معتبر نیست.")

    digits = [int(digit) for digit in value]
    total = sum(digits[i] * (10 - i) for i in range(9))
    remainder = total % 11
    expected = remainder if remainder < 2 else 11 - remainder

    if digits[9] != expected:
        raise ValidationError("رقم کنترلی کد ملی صحیح نیست.")


# اعتبارسنجی شماره تلفن ایران
def validate_iranian_phone(value):
    if not value:
        return

    value = normalize_digits(value)

    # قالب‌های مجاز: 09123456789 یا +989123456789
    if not re.fullmatch(r"(?:09\d{9}|\+989\d{9})", value):
        raise ValidationError(
            "شماره همراه باید مانند 09123456789 یا +989123456789 باشد."
        )


# نام و نام خانوادگی نباید صرفاً عدد باشند یا شامل علائم نامعتبر باشند.
name_validator = RegexValidator(
    regex=r"^[A-Za-z\u0600-\u06FF][A-Za-z\u0600-\u06FF\s'-]*$",
    message="نام باید با حروف فارسی یا انگلیسی شروع شود و شامل عدد نباشد.",
)



class Patient(models.Model):

    # Links the patient profile to a Django user account
    # Each user can have only one patient profile
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_profile",
        null=True,
        blank=True
    )

    # Stores the patient's first name
    first_name = models.CharField(
        max_length=100,
        validators=[name_validator],
    )

    # Stores the patient's last name
    last_name = models.CharField(
        max_length=100,
        validators=[name_validator],
    )

    # Stores the patient's unique national identification code
    # The field is optional, but duplicate values are not allowed
    national_code = models.CharField(
        max_length=10,
        unique=True,
        null=True,
        blank=True,
        validators=[validate_national_code],
    )

    # Stores the patient's phone number
    phone_number = models.CharField(
        max_length=13,
        validators=[validate_iranian_phone],
    )

    # Stores the patient's insurance type
    # This field is optional
    insurance_type = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    # Indicates whether the patient has sports insurance
    sports_insurance = models.BooleanField(default=False)

    # Performs additional validation and normalizes numeric characters
    def clean(self):
        super().clean()

        if self.national_code:
            self.national_code = normalize_digits(self.national_code)

        if self.phone_number:
            self.phone_number = normalize_digits(self.phone_number)

    # Normalizes numeric characters before saving the patient
    def save(self, *args, **kwargs):
        self.national_code = normalize_digits(self.national_code) or None
        self.phone_number = normalize_digits(self.phone_number)

        # Ensures normalized fields are included when using update_fields
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {
                "national_code",
                "phone_number",
            }

        super().save(*args, **kwargs)

    # Returns the patient's full name
    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    class Meta:
        # Sorts patients by last name and then first name
        ordering = ["last_name", "first_name"]

        # Adds indexes to improve search performance
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["phone_number"]),
        ]


class Doctor(models.Model):
    # The doctor's first name
    first_name = models.CharField(
        max_length=100,
        validators=[name_validator],
    )

    # The doctor's last name
    last_name = models.CharField(
        max_length=100,
        validators=[name_validator],
    )

    # Link the doctor profile to a Django user account
    # Each user can be linked to only one doctor profile
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="doctor_profile",
        null=True,
        blank=True,
    )

    # The doctor's medical specialty
    specialty = models.CharField(max_length=100)

    # Indicates whether the doctor is currently active
    is_active = models.BooleanField(default=True)

    # Default duration of an appointment in minutes
    appointment_duration = models.PositiveIntegerField(default=30)

    def __str__(self):
        # Return the doctor's full name
        return f"{self.first_name} {self.last_name}"

    class Meta:
        constraints = [
            # Ensure that the appointment duration is greater than zero
            models.CheckConstraint(
                condition=Q(appointment_duration__gt=0),
                name="doctor_appointment_duration_positive",
            ),
        ]


class Service(models.Model):
    # The unique name of the service
    service_name = models.CharField(max_length=100, unique=True)

    # Optional description of the service
    description = models.TextField(null=True, blank=True)

    # Duration of the service in minutes
    duration_minutes = models.PositiveIntegerField()

    # Cost of the service
    price = models.DecimalField(max_digits=10, decimal_places=2)

    # Determines whether the service is available for booking
    is_active = models.BooleanField(default=True)

    # Returns the service name as its string representation
    def __str__(self):
        return self.service_name

    class Meta:
        constraints = [
            # Ensures that the service duration is greater than zero
            models.CheckConstraint(
                condition=Q(duration_minutes__gt=0),
                name="service_duration_positive",
            ),

            # Ensures that the service price is not negative
            models.CheckConstraint(
                condition=Q(price__gte=0),
                name="service_price_nonnegative",
            ),
        ]


class DoctorSchedule(models.Model):
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="schedules",
    )
    schedule_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    def _has_overlap(self, lock=False):
        qs = DoctorSchedule.objects.filter(
            doctor_id=self.doctor_id,
            schedule_date=self.schedule_date,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        )
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        if lock:
            qs = qs.select_for_update()
        return bool(list(qs.values_list("pk", flat=True)[:1]))

    def _can_check(self):
        return bool(
            self.doctor_id and self.schedule_date and self.start_time
            and self.end_time and self.end_time > self.start_time
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            errors["end_time"] = "ساعت پایان باید بعد از ساعت شروع باشد."
        if self._can_check() and self._has_overlap():
            errors["start_time"] = "برنامه کاری با برنامه دیگری از همین پزشک تداخل دارد."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._can_check():
            with transaction.atomic():
                Doctor.objects.select_for_update().get(pk=self.doctor_id)
                if self._has_overlap(lock=True):
                    raise ValidationError(
                        {"start_time": "برنامه کاری با برنامه دیگری از همین پزشک تداخل دارد."}
                    )
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.doctor} - {self.schedule_date}"

    class Meta:
        ordering = ["schedule_date", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="schedule_end_after_start",
            ),
        ]
        indexes = [
            models.Index(fields=["doctor", "schedule_date"]),
        ]



class Appointment(models.Model):
    # Defines the possible appointment statuses.
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار تأیید"
        CONFIRMED = "confirmed", "تأیید شده"
        COMPLETED = "completed", "انجام شده"
        CANCELLED = "cancelled", "لغو شده"
        NO_SHOW = "no_show", "عدم مراجعه"

    # Links the appointment to the patient.
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="appointments",
    )

    # Links the appointment to the doctor.
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="appointments",
    )

    # Links the appointment to the doctor's work schedule.
    schedule = models.ForeignKey(
        DoctorSchedule,
        on_delete=models.PROTECT,
        # null=True,
        # blank=True,
        related_name="appointments",
    )

    # Specifies the service requested by the patient.
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        # null=True,
        # blank=True,
        related_name="appointments",
    )

    # Stores the appointment date and time range.
    appointment_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    # Stores the current status of the appointment.
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )

    # Automatically records when the appointment is created.
    created_at = models.DateTimeField(auto_now_add=True)

    # Fields that require revalidation when their values change.
    _TRACKED = (
        "doctor_id", "service_id", "schedule_id",
        "appointment_date", "start_time", "end_time",
    )

    def _has_conflict(self, lock=False):
        # Finds active appointments that overlap with this time slot.
        qs = Appointment.objects.filter(
            doctor_id=self.doctor_id,
            appointment_date=self.appointment_date,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        ).exclude(status=self.Status.CANCELLED)

        # Excludes the current appointment when updating it.
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        # Locks matching database rows when requested.
        if lock:
            qs = qs.select_for_update()

        # Returns True if at least one conflicting appointment exists.
        return bool(list(qs.values_list("pk", flat=True)[:1]))

    def _is_active_slot(self):
        # Checks whether the appointment occupies a valid, non-cancelled time slot.
        return bool(
            self.doctor_id and self.appointment_date and self.start_time
            and self.end_time and self.end_time > self.start_time
            and self.status != self.Status.CANCELLED
        )

    def clean(self):
        # Runs the default model validation.
        super().clean()
        errors = {}

        # Ensures that the end time is later than the start time.
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            errors["end_time"] = "ساعت پایان باید بعد از ساعت شروع باشد."

        # Retrieves the original appointment data when updating an existing record.
        orig = None
        if self.pk:
            orig = Appointment.objects.filter(pk=self.pk).values("status", *self._TRACKED).first()

        # Determines whether the appointment needs full validation.
        if orig is None:
            needs_full_check = True
        else:
            current = {field: getattr(self, field) for field in self._TRACKED}

            # Checks whether a cancelled appointment is being reactivated.
            reactivated = (
                orig["status"] == self.Status.CANCELLED
                and self.status != self.Status.CANCELLED
            )

            # Revalidates if any tracked field has changed.
            needs_full_check = reactivated or any(
                orig[field] != current[field] for field in self._TRACKED
            )

        if needs_full_check:
            # Prevents booking appointments with inactive doctors or services.
            if self.doctor_id and not self.doctor.is_active:
                errors["doctor"] = "برای پزشک غیرفعال نمی‌توان نوبت ثبت کرد."
            if self.service_id and not self.service.is_active:
                errors["service"] = "این خدمت غیرفعال است."

            # Checks whether the appointment duration matches the service or doctor's default duration.
            if self.start_time and self.end_time and self.doctor_id and self.appointment_date:
                from datetime import datetime, timedelta
                duration_minutes = (
                    self.service.duration_minutes if self.service_id
                    else self.doctor.appointment_duration
                )
                start = datetime.combine(self.appointment_date, self.start_time)
                end = datetime.combine(self.appointment_date, self.end_time)
                if end - start != timedelta(minutes=duration_minutes):
                    errors["end_time"] = "مدت نوبت باید با مدت خدمت یا مدت پیش‌فرض پزشک برابر باشد."

            # Validates the selected doctor's schedule.
            if self.schedule_id:
                if self.doctor_id and self.schedule.doctor_id != self.doctor_id:
                    errors["schedule"] = "برنامه کاری متعلق به این پزشک نیست."
                elif self.appointment_date and self.schedule.schedule_date != self.appointment_date:
                    errors["schedule"] = "تاریخ نوبت با تاریخ برنامه کاری یکسان نیست."
                elif self.start_time and self.end_time and (
                    self.start_time < self.schedule.start_time
                    or self.end_time > self.schedule.end_time
                ):
                    errors["start_time"] = "زمان نوبت باید در بازه برنامه کاری پزشک باشد."

            # Checks whether the appointment falls within any available schedule if no schedule is selected.
            elif self.doctor_id and self.appointment_date and self.start_time and self.end_time:
                if not DoctorSchedule.objects.filter(
                    doctor_id=self.doctor_id,
                    schedule_date=self.appointment_date,
                    start_time__lte=self.start_time,
                    end_time__gte=self.end_time,
                ).exists():
                    errors["start_time"] = "زمان نوبت خارج از ساعات کاری پزشک است."

        # Checks for overlapping appointments.
        if self._is_active_slot() and self._has_conflict():
            errors["start_time"] = "این بازه زمانی با نوبت دیگری از پزشک تداخل دارد."

        # Raises validation errors if any rule is violated.
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Applies concurrency protection for active appointments.
        if self._is_active_slot():
            with transaction.atomic():

                # Locks the doctor record to serialize concurrent bookings.
                Doctor.objects.select_for_update().get(pk=self.doctor_id)

                # Rechecks for conflicts before saving the appointment.
                if self._has_conflict(lock=True):
                    raise ValidationError(
                        {"start_time": "این بازه زمانی با نوبت دیگری از پزشک تداخل دارد."}
                    )

                # Saves the appointment inside the database transaction.
                return super().save(*args, **kwargs)

        # Saves cancelled or otherwise inactive appointments normally.
        return super().save(*args, **kwargs)

    def __str__(self):
        # Returns a readable representation of the appointment.
        return f"{self.patient} - {self.appointment_date}"

    class Meta:
        # Sorts appointments by date and then by start time.
        ordering = ["appointment_date", "start_time"]

        # Defines database-level constraints.
        constraints = [
            # Ensures that the end time is always later than the start time.
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="appointment_end_after_start",
            ),
        ]

        # Adds indexes to improve common database queries.
        indexes = [
            models.Index(fields=["doctor", "appointment_date", "start_time"]),
            models.Index(fields=["patient", "appointment_date"]),
            models.Index(fields=["status", "appointment_date"]),
        ]






class MedicalRecord(models.Model):
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="medical_records",
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="medical_records",
    )
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="medical_records",
    )
    record_date = models.DateTimeField(auto_now_add=True)
    description = models.TextField()
    diagnosis = models.TextField(null=True, blank=True)

    def clean(self):
        super().clean()
        errors = {}
        if self.appointment_id:
            appointment = self.appointment
            if self.patient_id and appointment.patient_id != self.patient_id:
                errors["patient"] = "بیمار پرونده باید با بیمار نوبت یکسان باشد."
            if self.doctor_id and appointment.doctor_id != self.doctor_id:
                errors["doctor"] = "پزشک پرونده باید با پزشک نوبت یکسان باشد."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Medical record {self.pk}"

    class Meta:
        ordering = ["-record_date"]
        indexes = [
            models.Index(fields=["patient", "record_date"]),
            models.Index(fields=["doctor", "record_date"]),
        ]


class PhysiotherapySession(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "برنامه‌ریزی شده"
        COMPLETED = "completed", "انجام شده"
        CANCELLED = "cancelled", "لغو شده"
        NO_SHOW = "no_show", "عدم مراجعه"

    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="physiotherapy_session",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="physiotherapy_sessions",
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="physiotherapy_sessions",
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="physiotherapy_sessions",
    )
    session_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )
    notes = models.TextField(null=True, blank=True)

    def clean(self):
        super().clean()
        errors = {}
        if self.appointment_id:
            appointment = self.appointment
            if self.patient_id and appointment.patient_id != self.patient_id:
                errors["patient"] = "بیمار جلسه باید با بیمار نوبت یکسان باشد."
            if self.doctor_id and appointment.doctor_id != self.doctor_id:
                errors["doctor"] = "درمانگر جلسه باید با پزشک نوبت یکسان باشد."
            if self.service_id and appointment.service_id and appointment.service_id != self.service_id:
                errors["service"] = "خدمت جلسه باید با خدمت نوبت یکسان باشد."
        if (
            self.start_time
            and self.end_time
            and self.end_time <= self.start_time
        ):
            errors["end_time"] = "ساعت پایان جلسه باید بعد از ساعت شروع باشد."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Session {self.pk}"

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="session_end_after_start",
            ),
        ]
        indexes = [
            models.Index(fields=["patient", "session_date"]),
            models.Index(fields=["doctor", "session_date"]),
        ]


class Notification(models.Model):
    class Type(models.TextChoices):
        SMS = "sms", "پیامک"
        EMAIL = "email", "ایمیل"
        SYSTEM = "system", "اعلان سیستمی"

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار ارسال"
        SENT = "sent", "ارسال شده"
        FAILED = "failed", "ناموفق"
        READ = "read", "خوانده شده"

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    message = models.TextField()
    notification_type = models.CharField(
        max_length=30,
        choices=Type.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification {self.pk}"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
        ]


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Audit log {self.pk}"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]


class InventoryItem(models.Model):
    item_name = models.CharField(max_length=150)
    category = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    minimum_quantity = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=30)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.item_name

    class Meta:
        ordering = ["item_name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=0),
                name="inventory_quantity_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(minimum_quantity__gte=0),
                name="inventory_minimum_nonnegative",
            ),
        ]


class InventoryTransaction(models.Model):
    class Type(models.TextChoices):
        IN = "in", "ورود کالا"
        OUT = "out", "خروج کالا"
        ADJUSTMENT_IN = "adjustment_in", "اصلاح موجودی (افزایش)"
        ADJUSTMENT_OUT = "adjustment_out", "اصلاح موجودی (کاهش)"

    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_transactions",
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=Type.choices,
    )
    quantity = models.PositiveIntegerField()
    transaction_date = models.DateTimeField(auto_now_add=True)
    description = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("تراکنش موجودی قابل ویرایش نیست.")
        if self.transaction_type not in self.Type.values:
            raise ValidationError({"transaction_type": "نوع تراکنش نامعتبر است."})
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({"quantity": "مقدار تراکنش باید بیشتر از صفر باشد."})

        increase = self.transaction_type in (self.Type.IN, self.Type.ADJUSTMENT_IN)
        with transaction.atomic():
            qs = InventoryItem.objects.filter(pk=self.item_id)
            if increase:
                updated = qs.update(quantity=F("quantity") + self.quantity)
            else:
                updated = qs.filter(quantity__gte=self.quantity).update(
                    quantity=F("quantity") - self.quantity
                )
            if not updated:
                raise ValidationError("موجودی کافی نیست یا کالا یافت نشد.")
            return super().save(*args, **kwargs)

    def __str__(self):
        return f"Inventory transaction {self.pk}"

    class Meta:
        ordering = ["-transaction_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="inventory_transaction_quantity_positive",
            ),
        ]
        indexes = [
            models.Index(fields=["item", "transaction_date"]),
            models.Index(fields=["transaction_type", "transaction_date"]),
        ]
