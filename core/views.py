
from openai import OpenAI

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from .models import DirectMessage
from .models import (
    College,
    Profile,
    Announcement,
    StudyMaterial,
    Event,
    StudentActivity,
    Notification,
    DirectMessage,
)


def get_user_role(user):
    try:
        return user.profile.role
    except Profile.DoesNotExist:
        return None


def home(request):
    return render(request, "core/home.html")



def register(request):
    colleges = College.objects.all().order_by("name")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")
        role = request.POST.get("role", "")
        college_id = request.POST.get("college", "")

        college = College.objects.filter(id=college_id).first()

        if not all([username, email, password, confirm_password, role, college_id]):
            messages.error(request, "Please complete all fields.")
        elif college is None:
            messages.error(request, "Please select a valid college.")
        elif role not in ("student", "faculty"):
            messages.error(request, "Please select a valid role.")
        elif password != confirm_password:
            messages.error(request, "Passwords do not match.")
        elif len(password) < 8:
            messages.error(request, "Password must contain at least 8 characters.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
        elif User.objects.filter(email__iexact=email).exists():
            messages.error(request, "Email already exists.")
        else:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
            )

            Profile.objects.create(
                user=user,
                role=role,
                college=college,
            )

            messages.success(
                request,
                "Registration successful. Please log in."
            )
            return redirect("login")

    return render(
        request,
        "core/register.html",
        {"colleges": colleges},
    )



def user_login(request):
    # Already logged-in users can go directly to their dashboard.
    # Logged-out users must enter their username and password.
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is None:
            messages.error(request, "Invalid username or password.")
        elif get_user_role(user) is None:
            messages.error(
                request, "Your account has no assigned role."
            )
        else:
            login(request, user)
            return redirect("dashboard")

    return render(request, "core/login.html")


@login_required
def user_logout(request):
    # Logout must be submitted using POST.
    if request.method != "POST":
        return redirect("dashboard")

    logout(request)
    messages.success(
        request, "You have been logged out successfully."
    )
    return redirect("logout_confirmation")


def logout_confirmation(request):
    # This page can be opened after logout.
    if request.user.is_authenticated:
        return redirect("dashboard")

    return render(request, "core/logout.html")


@login_required
def dashboard(request):
    role = get_user_role(request.user)

    if role == "faculty":
        return redirect("faculty_dashboard")
    elif role == "student":
        return redirect("student_dashboard")

    messages.error(request, "Your account role is not configured.")
    return redirect("home")


@login_required
def faculty_dashboard(request):
    if get_user_role(request.user) != "faculty":
        messages.error(request, "Faculty access only.")
        return redirect("dashboard")

    announcements = Announcement.objects.filter(
        created_by=request.user
    ).order_by("-created_at")

    study_materials = StudyMaterial.objects.filter(
        uploaded_by=request.user
    ).order_by("-uploaded_at")

    events = Event.objects.filter(
        created_by=request.user
    ).order_by("event_date")

    return render(request, "core/faculty_dashboard.html", {
        "announcements": announcements,
        "study_materials": study_materials,
        "events": events,
    })



@login_required
def student_dashboard(request):
    if get_user_role(request.user) != "student":
        messages.error(request, "Student access only.")
        return redirect("dashboard")

    college = request.user.profile.college

    announcements = Announcement.objects.filter(
        college=college
    ).order_by("-created_at")

    study_materials = StudyMaterial.objects.filter(
        college=college
    ).order_by("-uploaded_at")

    events = Event.objects.filter(
        college=college,
        event_date__gte=timezone.now()
    ).order_by("event_date")

    activities = StudentActivity.objects.filter(
        submitted_by=request.user
    ).order_by("-created_at")

    notifications = Notification.objects.filter(
        recipient=request.user
    ).select_related("announcement").order_by("-created_at")

    unread_count = notifications.filter(is_read=False).count()

    return render(request, "core/student_dashboard.html", {
        "announcements": announcements,
        "study_materials": study_materials,
        "events": events,
        "activities": activities,
        "notifications": notifications,
        "unread_count": unread_count,
    })




@login_required
def create_announcement(request):
    if get_user_role(request.user) != "faculty":
        messages.error(request, "Faculty access only.")
        return redirect("dashboard")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        message = request.POST.get("message", "").strip()

        if title and message:
            college = request.user.profile.college

            announcement = Announcement.objects.create(
                title=title,
                message=message,
                created_by=request.user,
                college=college,
            )

            if college:
                students = Profile.objects.filter(
                    college=college,
                    role="student",
                ).select_related("user")

                Notification.objects.bulk_create([
                    Notification(
                        recipient=student.user,
                        announcement=announcement,
                        message=f"New announcement: {announcement.title}",
                    )
                    for student in students
                ])

            messages.success(request, "Announcement published.")
            return redirect("faculty_dashboard")

        messages.error(request, "Please fill in all fields.")

    return render(request, "core/create_announcement.html")


@login_required
def upload_study_material(request):
    if get_user_role(request.user) != "faculty":
        messages.error(request, "Faculty access only.")
        return redirect("dashboard")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        uploaded_file = request.FILES.get("file")

        if not title or not uploaded_file:
            messages.error(request, "Title and file are required.")
        elif uploaded_file.size > 10 * 1024 * 1024:
            messages.error(
                request, "File size must not exceed 10 MB."
            )
        else:
            StudyMaterial.objects.create(
                title=title,
                description=description,
                file=uploaded_file,
                uploaded_by=request.user,
            )
            messages.success(request, "Study material uploaded.")
            return redirect("faculty_dashboard")

    return render(request, "core/upload_material.html")


@login_required
def create_event(request):
    if get_user_role(request.user) != "faculty":
        messages.error(request, "Faculty access only.")
        return redirect("dashboard")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        event_date = parse_datetime(
            request.POST.get("event_date", "")
        )
        venue = request.POST.get("venue", "").strip()

        if not all([title, description, event_date, venue]):
            messages.error(
                request, "Please fill in all fields correctly."
            )
        else:
            if timezone.is_naive(event_date):
                event_date = timezone.make_aware(event_date)

            Event.objects.create(
                title=title,
                description=description,
                event_date=event_date,
                venue=venue,
                created_by=request.user,
            )
            messages.success(request, "College event created.")
            return redirect("faculty_dashboard")

    return render(request, "core/create_event.html")


@login_required
def submit_activity(request):
    if get_user_role(request.user) != "student":
        messages.error(request, "Student access only.")
        return redirect("dashboard")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        activity_type = request.POST.get("activity_type", "")
        activity_date = parse_date(
            request.POST.get("activity_date", "")
        )

        valid_types = [
            choice[0] for choice in StudentActivity.ACTIVITY_TYPES
        ]

        if not all([title, description, activity_date]):
            messages.error(
                request, "Please fill in all fields correctly."
            )
        elif activity_type not in valid_types:
            messages.error(
                request, "Please select a valid activity type."
            )
        else:
            StudentActivity.objects.create(
                title=title,
                description=description,
                activity_type=activity_type,
                activity_date=activity_date,
                submitted_by=request.user,
            )
            messages.success(
                request, "Activity submitted successfully."
            )
            return redirect("student_dashboard")

    return render(request, "core/submit_activity.html")


@login_required
def faculty_activities(request):
    if get_user_role(request.user) != "faculty":
        messages.error(request, "Faculty access only.")
        return redirect("dashboard")

    activities = StudentActivity.objects.select_related(
        "submitted_by"
    ).order_by("-created_at")

    return render(request, "core/faculty_activities.html", {
        "activities": activities,
    })
@login_required
def ai_assistant(request):
    if request.method == "POST":
        question = request.POST.get("question", "").strip()

        if not question:
            messages.error(request, "Please enter a question.")
            return redirect("ai_assistant")

        try:
            client = OpenAI()

            response = client.responses.create(
                model="gpt-5.5",
                instructions=(
                    "You are the Smart College Connect AI Assistant. "
                    "Answer clearly and helpfully. Assist with education, "
                    "programming, careers, technology, and general questions. "
                    "If you do not know something, say so."
                ),
                input=question,
            )

            return render(
                request,
                "core/ai_assistant.html",
                {"answer": response.output_text, "question": question},
            )

       
        except Exception as e:
            print(f"AI Assistant error: {e}")
            messages.error(
                request,
                "The AI service failed. Check the VS Code terminal for details."
            )

    return render(request, "core/ai_assistant.html")

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Profile


@login_required
def profile_view(request):
    current_profile = request.user.profile
    college = current_profile.college

    faculty_profiles = Profile.objects.none()
    student_profiles = Profile.objects.none()
    student_count = 0

    if college:
        if current_profile.role == "student":
            faculty_profiles = Profile.objects.filter(
                college=college,
                role="faculty",
            ).select_related(
                "user", "college"
            ).order_by("user__username")

            # Count unread messages from each faculty member.
            for faculty in faculty_profiles:
                faculty.unread_count = DirectMessage.objects.filter(
                    sender=faculty.user,
                    recipient=request.user,
                    is_read=False,
                ).count()

        elif current_profile.role == "faculty":
            student_profiles = Profile.objects.filter(
                college=college,
                role="student",
            ).select_related(
                "user", "college"
            ).order_by("user__username")

            student_count = student_profiles.count()

            # Count unread messages from each student.
            for student in student_profiles:
                student.unread_count = DirectMessage.objects.filter(
                    sender=student.user,
                    recipient=request.user,
                    is_read=False,
                ).count()

    return render(
        request,
        "core/profile.html",
        {
            "profile": current_profile,
            "college": college,
            "faculty_profiles": faculty_profiles,
            "student_profiles": student_profiles,
            "student_count": student_count,
        },
    )


@login_required
def open_notification(request, notification_id):
    if get_user_role(request.user) != "student":
        messages.error(request, "Student access only.")
        return redirect("dashboard")

    notification = get_object_or_404(
        Notification,
        id=notification_id,
        recipient=request.user,
    )

    notification.is_read = True
    notification.save(update_fields=["is_read"])

    return redirect("student_dashboard")

@login_required
def conversation_view(request, user_id):
    current_profile = request.user.profile

    if current_profile.role not in ["student", "faculty"]:
        messages.error(request, "Messaging is available only to students and faculty.")
        return redirect("dashboard")

    other_user = get_object_or_404(
        User.objects.select_related("profile__college"),
        id=user_id,
    )

    other_profile = other_user.profile

    # Users can message only within the same college.
    if (
        current_profile.college is None
        or other_profile.college is None
        or current_profile.college_id != other_profile.college_id
    ):
        messages.error(request, "You can message users from your own college only.")
        return redirect("dashboard")

    # Prevent messaging yourself or unsupported roles.
    if (
        other_user == request.user
        or other_profile.role not in ["student", "faculty"]
    ):
        messages.error(request, "Invalid conversation.")
        return redirect("dashboard")

    if request.method == "POST":
        message_text = request.POST.get("message", "").strip()

        if message_text:
            DirectMessage.objects.create(
                sender=request.user,
                recipient=other_user,
                message=message_text,
            )
            return redirect("conversation", user_id=other_user.id)

        messages.error(request, "Please enter a message.")

    conversation_messages = DirectMessage.objects.filter(
        Q(sender=request.user, recipient=other_user)
        | Q(sender=other_user, recipient=request.user)
    ).select_related("sender", "recipient").order_by("created_at")

    # Mark messages received by the current user as read.
    DirectMessage.objects.filter(
        sender=other_user,
        recipient=request.user,
        is_read=False,
    ).update(is_read=True)

    return render(
        request,
        "core/conversation.html",
        {
            "other_user": other_user,
            "conversation_messages": conversation_messages,
        },
    )

@login_required
def inbox_view(request):
    current_profile = request.user.profile

    if current_profile.role not in ["student", "faculty"]:
        messages.error(
            request,
            "Messaging is available only to students and faculty."
        )
        return redirect("dashboard")

    if current_profile.college is None:
        messages.error(
            request,
            "Your profile has no college assigned."
        )
        return redirect("dashboard")

    # Find eligible users from the same college.
        # Students see faculty; faculty see students.
    target_role = (
        "faculty"
        if current_profile.role == "student"
        else "student"
    )

    available_users = User.objects.filter(
        profile__college=current_profile.college,
        profile__role=target_role,
    ).exclude(
        id=request.user.id
    ).select_related(
        "profile"
    ).order_by(
        "first_name", "username"
    )

    conversations = {}
    total_unread = 0

    for other_user in available_users:
        last_message = DirectMessage.objects.filter(
            Q(sender=request.user, recipient=other_user)
            | Q(sender=other_user, recipient=request.user)
        ).order_by("-created_at").first()

        unread_count = DirectMessage.objects.filter(
            sender=other_user,
            recipient=request.user,
            is_read=False,
        ).count()

        total_unread += unread_count

        conversations[other_user.id] = {
            "other_user": other_user,
            "last_message": last_message,
            "unread_count": unread_count,
        }

    return render(
        request,
        "core/inbox.html",
        {
            "conversations": list(conversations.values()),
            "total_unread": total_unread,
            "current_role": current_profile.role,
        },
    )
