from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import MarketReport


class UserRegistrationForm(UserCreationForm):
    age_confirmed = forms.BooleanField(
        required=True,
        label="I confirm I am 18 years of age or older",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)


class MarketReportForm(forms.ModelForm):
    class Meta:
        model = MarketReport
        fields = ["query"]
        widgets = {
            "query": forms.TextInput(
                attrs={
                    "maxlength": 255,
                    "placeholder": "Enter a company, product, or market",
                    "required": True,
                }
            )
        }
