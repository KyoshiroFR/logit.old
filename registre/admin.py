from django.contrib import admin

from .models import Equipment, Service

admin.site.site_header = "Administration LogIT"
admin.site.register([Equipment, Service])
