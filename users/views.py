import secrets
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from .models import NewsletterSubscription


@require_POST
def subscribe_newsletter(request):
	"""Handle newsletter subscription via email."""
	email = request.POST.get("email", "").strip().lower()
	
	if not email:
		if request.headers.get("X-Requested-With") == "XMLHttpRequest":
			return JsonResponse({"success": False, "message": "Email is required."}, status=400)
		messages.error(request, "Email is required.")
		return redirect(request.META.get("HTTP_REFERER", "/"))
	
	# Check if already subscribed
	subscription, created = NewsletterSubscription.objects.get_or_create(
		email=email,
		defaults={
			"verification_token": secrets.token_urlsafe(32),
			"is_subscribed": True,
			"is_verified": False,
		}
	)
	
	if created:
		# New subscription - return success
		if request.headers.get("X-Requested-With") == "XMLHttpRequest":
			return JsonResponse({
				"success": True,
				"message": "Thank you for subscribing! A verification email will be sent shortly."
			})
		messages.success(request, "Thank you for subscribing! A verification email will be sent shortly.")
	else:
		# Already subscribed
		if request.headers.get("X-Requested-With") == "XMLHttpRequest":
			return JsonResponse({
				"success": False,
				"message": "This email is already subscribed."
			})
		messages.info(request, "This email is already subscribed.")
	
	return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
def unsubscribe_newsletter(request):
	"""Unsubscribe from newsletter."""
	email = request.POST.get("email", "").strip().lower()
	
	try:
		subscription = NewsletterSubscription.objects.get(email=email)
		subscription.is_subscribed = False
		subscription.save(update_fields=["is_subscribed"])
		
		if request.headers.get("X-Requested-With") == "XMLHttpRequest":
			return JsonResponse({"success": True, "message": "You have been unsubscribed."})
		messages.success(request, "You have been unsubscribed.")
	except NewsletterSubscription.DoesNotExist:
		if request.headers.get("X-Requested-With") == "XMLHttpRequest":
			return JsonResponse({
				"success": False,
				"message": "Email not found in our newsletter list."
			})
		messages.error(request, "Email not found in our newsletter list.")
	
	return redirect(request.META.get("HTTP_REFERER", "/"))
