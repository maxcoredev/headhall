import datetime
from base.ubla import since, intersects
from base.exceptions import CommonError
from django.http.response import JsonResponse
from apps.security.models import BadIp, ACTION_RULES, ACTION_TRIES, ACTION_FAILS
from apps.security.models import IpActing, BrowserActing, UserActing


# Убеждаемся, что есть куда записывать
def ensure_actings(get_response):
    def middleware(request):
        if request.ip and not request.ip.acting:
            request.ip.acting = IpActing.objects.create()
            request.ip.save()
        if request.browser and not request.browser.acting:
            request.browser.acting = BrowserActing.objects.create()
            request.browser.save()
        if request.me and not request.me.acting:
            request.me.acting = UserActing.objects.create()
            request.me.save()
        response = get_response(request)
        return response

    return middleware


# Если кто-то пытается подобрать куку Браузера — трекаем неудачные попытки
def browser_security(get_response):
    def middleware(request):
        browser_key = request.COOKIES.get('browser_key')
        delete_cookie = False
        if browser_key and not request.browser:
            for actor in filter(None, [request.ip, request.me]):
                actor.acting.increment('BROWSER')
            delete_cookie = True
        response = get_response(request)
        if delete_cookie:
            response.delete_cookie('browser_key')
        return response
    return middleware


# Если кто-то пытается подобрать куку Сеанса — трекаем неудачные попытки
def seance_security(get_response):
    def middleware(request):
        seance_key = request.COOKIES.get('seance_key')
        delete_cookie = False
        if seance_key and not request.me:
            for actor in filter(None, [request.ip, request.browser]):
                actor.acting.increment('SEANCE')
            delete_cookie = True
        response = get_response(request)
        if delete_cookie:
            response.delete_cookie('seance_key')
        return response
    return middleware


# Если кто-то пытается подобрать куку Сессии (админки) — трекаем неудачные попытки
def session_security(get_response):
    def middleware(request):
        sessionid = request.COOKIES.get('sessionid')
        delete_cookie = False
        if sessionid and not request.user:
            for actor in filter(None, [request.ip, request.browser, request.me]):
                actor.acting.increment('SESSION')
            delete_cookie = True
        response = get_response(request)
        if delete_cookie:
            response.delete_cookie('sessionid')
        return response
    return middleware


# Трекаем GET и POST запросы
def requests(get_response):
    def middleware(request):

        request.actions = [request.method.upper()]

        if request.method == 'GET':
            for actor in filter(None, [request.ip, request.browser, request.me]):
                actor.acting.increment('GET')
        elif request.method == 'POST':
            for actor in filter(None, [request.ip, request.browser, request.me]):
                actor.acting.increment('POST')
        else:
            raise CommonError('METHOD_NOT_ALLOWED')

        for ACTION, urls in ACTION_TRIES.items():
            if request.path in urls:
                request.actions.append(ACTION)
                for actor in filter(None, [request.ip, request.browser, request.me]):
                    setattr(actor.acting, ACTION, getattr(actor.acting, ACTION) + 1)
                    setattr(actor.acting, f'last_{ACTION}_at', datetime.datetime.utcnow())
                    actor.acting.save()

        for ACTION, urls in ACTION_FAILS.items():
            if request.path in urls:
                request.actions.append(ACTION)

        response = get_response(request)

        for ACTION, urls in ACTION_FAILS.items():
            if request.path in urls and 400 <= response.status_code < 500:
                for actor in filter(None, [request.ip, request.browser, request.me]):
                    setattr(actor.acting, ACTION, getattr(actor.acting, ACTION) + 1)
                    setattr(actor.acting, f'last_{ACTION}_at', datetime.datetime.utcnow())
                    actor.acting.save()

        return response
    return middleware


# Проверяем плохие IP, очищаем треки, навешиваем подозрения, снимаем подозрения, ограничиваем подозрительных и забаненых
def security(get_response):
    def middleware(request):

        # Нет ли текущего IP среди плохих?
        bad_ip = BadIp.objects.filter(ip_address=request.ip.ip_address, is_not_fair=False, suspected_count__gt=1).first()
        if bad_ip:
            raise CommonError('BAD_IP')

        for actor in filter(None, [request.ip, request.browser, request.me]):
            actor_name = actor.__class__.__name__

            # Ранее, в миддлварах и вьюхах — мы трекали действия; теперь:

            for ACTION, rules in ACTION_RULES.items():
                timer = f'last_{ACTION}_at'

                actions_limit = rules[actor_name]
                per = rules['per']

                # 1. Может прошло достаточно, чтобы очистить трек?
                if getattr(actor.acting, timer) and since(getattr(actor.acting, timer), passed_more_than=per):
                    setattr(actor.acting, ACTION, 0)
                    setattr(actor.acting, timer, None)
                    actor.acting.save()

                # 2. Или, наоборот — это уже становится подозрительным?
                elif getattr(actor.acting, ACTION) >= actions_limit:
                    actor.is_suspicious = True
                    actor.suspicious_reason = ACTION
                    actor.suspected_at = datetime.datetime.utcnow()
                    actor.suspicious_count += 1
                    actor.save()

            # 3. Снимаем установленные ранее подозрения, если прошло достаточно времени
            if actor.is_suspicious:
                for_a = ACTION_RULES[actor.suspicious_reason]['for_a']
                if since(actor.suspected_at, passed_more_than=for_a):
                    actor.is_suspicious = False
                    actor.save()

        # После того как мы привели в порядок все счётчики и подозрения — ограничиваем подозрительных и забаненных
        for actor in filter(None, [request.ip, request.browser, request.me]):

            # Ограничиваем запросы подозрительных
            if actor.is_suspicious:
                actions_to_restrict_for_that_suspicioun = ACTION_RULES[actor.suspicious_reason]['rest']
                if intersects(actions_to_restrict_for_that_suspicioun, request.actions):
                    raise CommonError(actor.suspicious_reason)

            # Ограничиваем забаненных
            if actor.is_banned:
                raise CommonError(actor.ban_reason)

        response = get_response(request)
        return response
    return middleware
