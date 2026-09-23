from django.urls import path

from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),

    path('autores/', views.lista_autores, name='lista_autores'),
    path('autores/novo/', views.novo_autor, name='novo_autor'),
    path('autores/<int:pk>/editar/', views.editar_autor, name='editar_autor'),
    path('autores/<int:pk>/excluir/', views.excluir_autor, name='excluir_autor'),

    path('livros/', views.lista_livros, name='lista_livros'),
    path('livros/novo/', views.novo_livro, name='novo_livro'),
    path('livros/<int:pk>/', views.livro_detalhe, name='livro_detalhe'),
    path('livros/<int:pk>/editar/', views.editar_livro, name='editar_livro'),
    path('livros/<int:pk>/excluir/', views.excluir_livro, name='excluir_livro'),

    path('exemplares/', views.lista_exemplares, name='lista_exemplares'),
    path('exemplares/novo/', views.novo_exemplar, name='novo_exemplar'),
    path('exemplares/<int:pk>/editar/', views.editar_exemplar, name='editar_exemplar'),
    path('exemplares/<int:pk>/excluir/', views.excluir_exemplar, name='excluir_exemplar'),

    path('membros/', views.lista_membros, name='lista_membros'),
    path('membros/novo/', views.novo_membro, name='novo_membro'),
    path('membros/<int:pk>/', views.membro_detalhe, name='membro_detalhe'),
    path('membros/<int:pk>/editar/', views.editar_membro, name='editar_membro'),
    path('membros/<int:pk>/excluir/', views.excluir_membro, name='excluir_membro'),
]
