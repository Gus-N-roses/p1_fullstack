from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from acervo.views import Entrar

urlpatterns = [
    path('admin/', admin.site.urls),
    path('entrar/', Entrar.as_view(), name='login'),
    path('sair/', auth_views.LogoutView.as_view(), name='logout'),
    path('api/', include('acervo.api_urls')),
    path('api-auth/', include('rest_framework.urls')),  # login da Browsable API
    path('', include('acervo.urls')),
]
