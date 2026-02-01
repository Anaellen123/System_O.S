from django.shortcuts import render

def index(request):
    return render(request, "index.html")

def solicitar_servico(request):
    return render(request, "solicitar_servico.html")

def login_admin(request):
    return render(request, "login_admin.html")

def solicitar(request):
    if request.method == "POST":
        tipo_servico = request.POST.get("tipo_servico")
        descricao = request.POST.get("descricao")
        # salvar no banco
    return render(request, "solicitar_servico.html")
