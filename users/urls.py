from django.urls import path
from . import views

app_name = "users"

urlpatterns = [
	path("newsletter/subscribe/", views.subscribe_newsletter, name="subscribe_newsletter"),
	path("newsletter/unsubscribe/", views.unsubscribe_newsletter, name="unsubscribe_newsletter"),
]
