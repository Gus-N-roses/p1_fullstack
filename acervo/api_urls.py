from django.urls import path

from . import api_views as api

urlpatterns = [
    path('dashboard/', api.DashboardApi.as_view(), name='api_dashboard'),

    path('autores/', api.AutorListCreate.as_view(), name='api_autores'),
    path('autores/<int:pk>/', api.AutorDetail.as_view(), name='api_autor'),

    path('livros/', api.LivroListCreate.as_view(), name='api_livros'),
    path('livros/<int:pk>/', api.LivroDetail.as_view(), name='api_livro'),

    path('exemplares/', api.ExemplarListCreate.as_view(), name='api_exemplares'),
    path('exemplares/<int:pk>/', api.ExemplarDetail.as_view(), name='api_exemplar'),

    path('membros/', api.MembroListCreate.as_view(), name='api_membros'),
    path('membros/<int:pk>/', api.MembroDetail.as_view(), name='api_membro'),

    path('emprestimos/', api.EmprestimoListCreate.as_view(), name='api_emprestimos'),
    path('emprestimos/<int:pk>/', api.EmprestimoDetail.as_view(), name='api_emprestimo'),
    path('emprestimos/<int:pk>/devolver/', api.DevolverEmprestimo.as_view(), name='api_devolver'),
    path('emprestimos/<int:pk>/pagar-multa/', api.PagarMulta.as_view(), name='api_pagar_multa'),

    path('reservas/', api.ReservaListCreate.as_view(), name='api_reservas'),
    path('reservas/<int:pk>/', api.ReservaDetail.as_view(), name='api_reserva'),
    path('reservas/<int:pk>/cancelar/', api.CancelarReserva.as_view(), name='api_cancelar_reserva'),
]
