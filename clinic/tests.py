
from datetime import date, time
import threading

from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, close_old_connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase

from .models import (
    Patient,
    Doctor,
    Service,
    DoctorSchedule,
    Appointment,
    InventoryItem,
    InventoryTransaction,
)


class AppointmentTests(TestCase):
    """تست قوانین رزرو نوبت و برنامه کاری پزشک."""

    def setUp(self):
        self.patient = Patient.objects.create(
            first_name="علی",
            last_name="رضایی",
            phone_number="09123456789",
        )

        self.doctor = Doctor.objects.create(
            first_name="محمد",
            last_name="احمدی",
            specialty="فیزیوتراپی",
            is_active=True,
            appointment_duration=30,
        )

        self.service = Service.objects.create(
            service_name="فیزیوتراپی عمومی",
            duration_minutes=30,
            price="200000.00",
            is_active=True,
        )

        self.other_doctor = Doctor.objects.create(
            first_name="رضا",
            last_name="کریمی",
            specialty="فیزیوتراپی",
            appointment_duration=30,
        )

        self.appointment_date = date(2030, 5, 20)

        self.schedule = DoctorSchedule.objects.create(
            doctor=self.doctor,
            schedule_date=self.appointment_date,
            start_time=time(9, 0),
            end_time=time(12, 0),
        )

    def make_appointment(self, **kwargs):
        data = {
            "patient": self.patient,
            "doctor": self.doctor,
            "schedule": self.schedule,
            "service": self.service,
            "appointment_date": self.appointment_date,
            "start_time": time(9, 0),
            "end_time": time(9, 30),
            "status": Appointment.Status.CONFIRMED,
        }
        data.update(kwargs)
        return Appointment(**data)

    def test_valid_appointment_can_be_saved(self):
        """رزرو معتبر باید در دیتابیس ذخیره شود."""
        appointment = self.make_appointment()
        appointment.full_clean()
        appointment.save()

        self.assertTrue(
            Appointment.objects.filter(pk=appointment.pk).exists()
        )

    def test_overlapping_appointment_is_rejected(self):
        """نوبت هم‌پوشان برای همان پزشک نباید ثبت شود."""
        self.make_appointment().save()

        overlapping = self.make_appointment(
            start_time=time(9, 15),
            end_time=time(9, 45),
        )

        with self.assertRaises(ValidationError):
            overlapping.save()

        self.assertEqual(Appointment.objects.count(), 1)

    def test_adjacent_appointments_are_allowed(self):
        """نوبت‌هایی که فقط مرز زمانی مشترک دارند، مجازند."""
        self.make_appointment().save()

        adjacent = self.make_appointment(
            start_time=time(9, 30),
            end_time=time(10, 0),
        )
        adjacent.full_clean()
        adjacent.save()

        self.assertEqual(Appointment.objects.count(), 2)

    def test_cancelled_appointment_does_not_block_slot(self):
        """نوبت لغوشده نباید مانع رزرو همان بازه شود."""
        self.make_appointment(
            status=Appointment.Status.CANCELLED
        ).save()

        new_appointment = self.make_appointment()
        new_appointment.full_clean()
        new_appointment.save()

        self.assertEqual(Appointment.objects.count(), 2)

    def test_cancelled_appointment_can_be_rebooked(self):
        """بازه نوبت لغوشده باید دوباره قابل رزرو باشد."""
        cancelled = self.make_appointment(
            status=Appointment.Status.CANCELLED
        )
        cancelled.save()

        replacement = self.make_appointment()
        replacement.full_clean()
        replacement.save()

        self.assertEqual(Appointment.objects.count(), 2)

    def test_inactive_doctor_is_rejected(self):
        self.doctor.is_active = False
        self.doctor.save()

        appointment = self.make_appointment()

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_inactive_service_is_rejected(self):
        self.service.is_active = False
        self.service.save()

        appointment = self.make_appointment()

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_wrong_appointment_duration_is_rejected(self):
        """مدت نوبت باید با مدت خدمت برابر باشد."""
        appointment = self.make_appointment(
            start_time=time(9, 0),
            end_time=time(9, 45),
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_appointment_outside_schedule_is_rejected(self):
        appointment = self.make_appointment(
            start_time=time(11, 45),
            end_time=time(12, 15),
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_schedule_of_another_doctor_is_rejected(self):
        other_schedule = DoctorSchedule.objects.create(
            doctor=self.other_doctor,
            schedule_date=self.appointment_date,
            start_time=time(9, 0),
            end_time=time(12, 0),
        )

        appointment = self.make_appointment(schedule=other_schedule)

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_schedule_with_wrong_date_is_rejected(self):
        wrong_date_schedule = DoctorSchedule.objects.create(
            doctor=self.doctor,
            schedule_date=date(2030, 5, 21),
            start_time=time(9, 0),
            end_time=time(12, 0),
        )

        appointment = self.make_appointment(
            schedule=wrong_date_schedule
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_end_time_must_be_after_start_time(self):
        appointment = self.make_appointment(
            start_time=time(9, 30),
            end_time=time(9, 0),
        )

        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_schedule_overlap_is_rejected(self):
        overlapping_schedule = DoctorSchedule(
            doctor=self.doctor,
            schedule_date=self.appointment_date,
            start_time=time(11, 0),
            end_time=time(13, 0),
        )

        with self.assertRaises(ValidationError):
            overlapping_schedule.save()

        self.assertEqual(DoctorSchedule.objects.count(), 1)


class InventoryTests(TestCase):
    """تست ورود، خروج و گردش موجودی انبار."""

    def setUp(self):
        self.item = InventoryItem.objects.create(
            item_name="باند کشی",
            category="مصرفی",
            quantity=10,
            minimum_quantity=3,
            unit="عدد",
            is_active=True,
        )

    def make_transaction(self, **kwargs):
        data = {
            "item": self.item,
            "transaction_type": InventoryTransaction.Type.IN,
            "quantity": 5,
            "description": "تست موجودی",
        }
        data.update(kwargs)
        return InventoryTransaction(**data)

    def test_stock_increases_after_goods_receipt(self):
        transaction = self.make_transaction(
            transaction_type=InventoryTransaction.Type.IN,
            quantity=5,
        )
        transaction.save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 15)
        self.assertTrue(
            InventoryTransaction.objects.filter(
                pk=transaction.pk
            ).exists()
        )

    def test_stock_decreases_after_goods_issue(self):
        transaction = self.make_transaction(
            transaction_type=InventoryTransaction.Type.OUT,
            quantity=4,
        )
        transaction.save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 6)

    def test_adjustment_increases_stock(self):
        self.make_transaction(
            transaction_type=InventoryTransaction.Type.ADJUSTMENT_IN,
            quantity=3,
        ).save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 13)

    def test_adjustment_decreases_stock(self):
        self.make_transaction(
            transaction_type=InventoryTransaction.Type.ADJUSTMENT_OUT,
            quantity=3,
        ).save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 7)

    def test_insufficient_stock_is_rejected(self):
        transaction = self.make_transaction(
            transaction_type=InventoryTransaction.Type.OUT,
            quantity=11,
        )

        with self.assertRaises(ValidationError):
            transaction.save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)
        self.assertEqual(InventoryTransaction.objects.count(), 0)

    def test_zero_quantity_is_rejected(self):
        transaction = self.make_transaction(quantity=0)

        with self.assertRaises(ValidationError):
            transaction.save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)
        self.assertEqual(InventoryTransaction.objects.count(), 0)

    def test_negative_quantity_is_rejected(self):
        transaction = self.make_transaction(quantity=-2)

        with self.assertRaises(ValidationError):
            transaction.save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)

    def test_invalid_transaction_type_is_rejected(self):
        transaction = self.make_transaction(
            transaction_type="invalid_type"
        )

        with self.assertRaises(ValidationError):
            transaction.save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)
        self.assertEqual(InventoryTransaction.objects.count(), 0)

    def test_saved_transaction_cannot_be_updated(self):
        transaction = self.make_transaction(quantity=2)
        transaction.save()

        transaction.quantity = 4

        with self.assertRaises(ValidationError):
            transaction.save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 12)

        transaction.refresh_from_db()
        self.assertEqual(transaction.quantity, 2)

    def test_multiple_transactions_update_stock_correctly(self):
        self.make_transaction(
            transaction_type=InventoryTransaction.Type.IN,
            quantity=5,
        ).save()

        self.make_transaction(
            transaction_type=InventoryTransaction.Type.OUT,
            quantity=8,
        ).save()

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 7)
        self.assertEqual(InventoryTransaction.objects.count(), 2)

    def test_transaction_history_is_preserved(self):
        self.make_transaction(
            transaction_type=InventoryTransaction.Type.IN,
            quantity=5,
        ).save()

        self.make_transaction(
            transaction_type=InventoryTransaction.Type.OUT,
            quantity=3,
        ).save()

        self.assertEqual(InventoryTransaction.objects.count(), 2)


class DatabaseIntegrityTests(TestCase):
    """روابط خارجی و محدودیت‌های واقعی دیتابیس."""

    def setUp(self):
        self.patient = Patient.objects.create(
            first_name="علی",
            last_name="رضایی",
            national_code="1234567890",
            phone_number="09123456789",
        )
        self.doctor = Doctor.objects.create(
            first_name="محمد",
            last_name="احمدی",
            specialty="فیزیوتراپی",
            appointment_duration=30,
        )
        self.service = Service.objects.create(
            service_name="خدمت آزمایشی",
            duration_minutes=30,
            price="100000.00",
        )
        self.schedule = DoctorSchedule.objects.create(
            doctor=self.doctor,
            schedule_date=date(2030, 5, 20),
            start_time=time(9, 0),
            end_time=time(12, 0),
        )
        self.appointment = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            service=self.service,
            schedule=self.schedule,
            appointment_date=date(2030, 5, 20),
            start_time=time(9, 0),
            end_time=time(9, 30),
        )
        self.item = InventoryItem.objects.create(
            item_name="باند",
            category="مصرفی",
            quantity=10,
            minimum_quantity=2,
            unit="عدد",
        )
        InventoryTransaction.objects.create(
            item=self.item,
            transaction_type=InventoryTransaction.Type.IN,
            quantity=2,
        )

    def test_national_code_must_be_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Patient.objects.create(
                    first_name="رضا",
                    last_name="کریمی",
                    national_code=self.patient.national_code,
                    phone_number="09123456780",
                )

    def test_patient_protects_appointment(self):
        with self.assertRaises(ProtectedError):
            self.patient.delete()

    def test_doctor_protects_appointment(self):
        with self.assertRaises(ProtectedError):
            self.doctor.delete()

    def test_service_protects_appointment(self):
        with self.assertRaises(ProtectedError):
            self.service.delete()

    def test_schedule_protects_appointment(self):
        with self.assertRaises(ProtectedError):
            self.schedule.delete()

    def test_item_protects_transaction_history(self):
        with self.assertRaises(ProtectedError):
            self.item.delete()

    def test_doctor_duration_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Doctor.objects.filter(pk=self.doctor.pk).update(
                    appointment_duration=0
                )

    def test_service_duration_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Service.objects.filter(pk=self.service.pk).update(
                    duration_minutes=0
                )

    def test_service_price_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Service.objects.filter(pk=self.service.pk).update(
                    price="-1.00"
                )

    def test_schedule_end_time_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DoctorSchedule.objects.filter(
                    pk=self.schedule.pk
                ).update(end_time=time(8, 0))

    def test_appointment_end_time_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appointment.objects.filter(
                    pk=self.appointment.pk
                ).update(end_time=time(9, 0))

    def test_inventory_quantity_check_constraint(self):
        with self.assertRaises((IntegrityError, DataError)):
            with transaction.atomic():
                InventoryItem.objects.filter(
                    pk=self.item.pk
                ).update(quantity=-1)

    def test_inventory_minimum_check_constraint(self):
        with self.assertRaises((IntegrityError, DataError)):
            with transaction.atomic():
                InventoryItem.objects.filter(
                    pk=self.item.pk
                ).update(minimum_quantity=-1)

    def test_transaction_quantity_check_constraint(self):
        tx = InventoryTransaction.objects.get(item=self.item)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InventoryTransaction.objects.filter(
                    pk=tx.pk
                ).update(quantity=0)



class AppointmentConcurrencyTests(TransactionTestCase):
    """بررسی جلوگیری از ثبت هم‌زمان دو نوبت متداخل در دیتابیس واقعی."""

    reset_sequences = True

    def setUp(self):
        self.patient = Patient.objects.create(
            first_name="علی",
            last_name="رضایی",
            phone_number="09123456789",
        )
        self.doctor = Doctor.objects.create(
            first_name="محمد",
            last_name="احمدی",
            specialty="فیزیوتراپی",
            is_active=True,
            appointment_duration=30,
        )
        self.service = Service.objects.create(
            service_name="خدمت هم‌زمانی",
            duration_minutes=30,
            price="100000.00",
            is_active=True,
        )
        self.appointment_date = date(2030, 5, 20)
        self.schedule = DoctorSchedule.objects.create(
            doctor=self.doctor,
            schedule_date=self.appointment_date,
            start_time=time(9, 0),
            end_time=time(12, 0),
        )

    def test_only_one_overlapping_appointment_succeeds_concurrently(self):
        barrier = threading.Barrier(2)
        results = []
        results_lock = threading.Lock()

        def create_appointment():
            close_old_connections()
            try:
                patient = Patient.objects.get(pk=self.patient.pk)
                doctor = Doctor.objects.get(pk=self.doctor.pk)
                service = Service.objects.get(pk=self.service.pk)
                schedule = DoctorSchedule.objects.get(pk=self.schedule.pk)
                appointment = Appointment(
                    patient=patient,
                    doctor=doctor,
                    service=service,
                    schedule=schedule,
                    appointment_date=self.appointment_date,
                    start_time=time(9, 0),
                    end_time=time(9, 30),
                    status=Appointment.Status.CONFIRMED,
                )
                barrier.wait(timeout=10)
                try:
                    appointment.save()
                    result = "saved"
                except (ValidationError, IntegrityError) as exc:
                    result = "rejected"
                with results_lock:
                    results.append(result)
            except Exception as exc:
                with results_lock:
                    results.append(f"error: {type(exc).__name__}: {exc}")
            finally:
                close_old_connections()

        threads = [
            threading.Thread(target=create_appointment),
            threading.Thread(target=create_appointment),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertTrue(all(not thread.is_alive() for thread in threads),
                        "یکی از threadها در زمان مقرر تمام نشد.")
        self.assertEqual(results.count("saved"), 1, results)
        self.assertEqual(results.count("rejected"), 1, results)
        self.assertEqual(Appointment.objects.count(), 1)


class InventoryAtomicityTests(TransactionTestCase):
    """بررسی اتمیک بودن ثبت گردش انبار و جلوگیری از موجودی منفی."""

    reset_sequences = True

    def setUp(self):
        self.item = InventoryItem.objects.create(
            item_name="باند آزمایشی",
            category="مصرفی",
            quantity=10,
            minimum_quantity=2,
            unit="عدد",
            is_active=True,
        )

    def test_stock_and_history_roll_back_with_outer_transaction(self):
        try:
            with transaction.atomic():
                InventoryTransaction.objects.create(
                    item=self.item,
                    transaction_type=InventoryTransaction.Type.IN,
                    quantity=5,
                    description="تست rollback",
                )
                self.item.refresh_from_db()
                self.assertEqual(self.item.quantity, 15)
                raise RuntimeError("rollback test")
        except RuntimeError:
            pass

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)
        self.assertEqual(InventoryTransaction.objects.count(), 0)

    def test_concurrent_outgoing_transactions_do_not_make_stock_negative(self):
        barrier = threading.Barrier(2)
        results = []
        results_lock = threading.Lock()

        def issue_goods():
            close_old_connections()
            try:
                item = InventoryItem.objects.get(pk=self.item.pk)
                tx = InventoryTransaction(
                    item=item,
                    transaction_type=InventoryTransaction.Type.OUT,
                    quantity=7,
                    description="تست خروج هم‌زمان",
                )
                barrier.wait(timeout=10)
                try:
                    tx.save()
                    result = "saved"
                except (ValidationError, IntegrityError, DataError):
                    result = "rejected"
                with results_lock:
                    results.append(result)
            except Exception as exc:
                with results_lock:
                    results.append(f"error: {type(exc).__name__}: {exc}")
            finally:
                close_old_connections()

        threads = [
            threading.Thread(target=issue_goods),
            threading.Thread(target=issue_goods),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertTrue(all(not thread.is_alive() for thread in threads),
                        "یکی از threadها در زمان مقرر تمام نشد.")
        self.assertEqual(results.count("saved"), 1, results)
        self.assertEqual(results.count("rejected"), 1, results)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 3)
        self.assertEqual(InventoryTransaction.objects.count(), 1)

from django.test import TestCase
from .models import Patient
from .serializers import PatientSerializer


class PatientSerializerTests(TestCase):

    def setUp(self):
        self.valid_data = {
            "first_name": "علی",
            "last_name": "رضایی",
            "national_code": "0084575948",
            "phone_number": "09123456789",
        }

    def test_valid_patient_data(self):
        serializer = PatientSerializer(data=self.valid_data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_invalid_national_code(self):
        data = self.valid_data.copy()
        data["national_code"] = "1234567892"

        serializer = PatientSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("national_code", serializer.errors)

    def test_invalid_phone_number(self):
        data = self.valid_data.copy()
        data["phone_number"] = "12345"

        serializer = PatientSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("phone_number", serializer.errors)

    def test_persian_digits_are_normalized(self):
        data = self.valid_data.copy()
        data["national_code"] = "۰۰۸۴۵۷۵۹۴۸"
        data["phone_number"] = "۰۹۱۲۳۴۵۶۷۸۹"

        serializer = PatientSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["national_code"],
            "0084575948",
        )
        self.assertEqual(
            serializer.validated_data["phone_number"],
            "09123456789",
        )

    def test_duplicate_national_code(self):
        first_serializer = PatientSerializer(data=self.valid_data)
        first_serializer.is_valid(raise_exception=True)
        first_serializer.save()

        second_serializer = PatientSerializer(data=self.valid_data)

        self.assertFalse(second_serializer.is_valid())
        self.assertIn("national_code", second_serializer.errors)
