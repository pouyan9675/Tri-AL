import datetime

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib import messages, admin
from django.forms.widgets import Widget
from django.utils.safestring import mark_safe
from django import forms
from daterangefilter.filters import DateRangeFilter


class ItemView(Widget):

    template_name = 'forms/widgets/item_view.html'

    def __init__(self, attrs=None):
        if attrs is not None:
            attrs = attrs.copy()
            attrs['list_items'] = self.itemize(attrs['list_items'])
        super().__init__(attrs)

    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        return context

    
    def itemize(self, items):
        text = [mark_safe(x) for x in items]
        if len(text) > 1:
            return text
        elif len(text) == 1 and text[0] != '':
            return text
        else:
            return []


class TextView(Widget):

    template_name = 'forms/widgets/text_view.html'

    def __init__(self, attrs=None):
        if attrs is not None:
            attrs = attrs.copy()
        super().__init__(attrs)

    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        return context


class ProcessedView(Widget):

    template_name = 'forms/widgets/processed_view.html'

    def __init__(self, attrs=None):
        if attrs is not None:
            attrs = attrs.copy()
        super().__init__(attrs)

    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        return context


class DateRangePicker(Widget):
    
    template_name = 'admin/widgets/date_range_picker.html'

    
    class Media:
        css = {
            'all': ('admin/css/vendor/daterangepicker/daterangepicker.css',),
        }

        js = (
                'admin/js/vendor/daterangepicker/moment.min.js',
                'admin/js/vendor/daterangepicker/daterangepicker.js',
            )


    def __init__(self, attrs=None):
        if attrs is not None:
            attrs = attrs.copy()

        

        super().__init__(attrs)


    def get_context(self, name, value, attrs):
        if value is None:
            value = 'Pick a Date Range'
        return super().get_context(name, value, attrs)



class AutocompleteMixin(admin.widgets.AutocompleteMixin):
    """
        Override the class in order to remove the Jquery addon and use the 
        latest jquery in the whole project.
    """

    @property
    def media(self):
        extra = '' if settings.DEBUG else '.min'
        

        return forms.Media(
            js=(
                'admin/js/vendor/select2/select2.full%s.js' % extra,
            ) + (
                # 'admin/js/jquery.init.js',
                'admin/js/autocomplete.js',
            ),
            css={
                'screen': (
                    'admin/css/vendor/select2/select2%s.css' % extra,
                    'admin/css/autocomplete.css',
                ),
            },
        )



class AutocompleteSelectMultiple(AutocompleteMixin, forms.SelectMultiple):
    pass