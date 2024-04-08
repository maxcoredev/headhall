import datetime
from django.db import transaction
from django.db import models


class Actions(models.TextChoices):
    GET     = 'GET',     'Слишком много GET-запросов'
    POST    = 'POST',    'Слишком много POST-запросов'
    MAIL    = 'MAIL',    'Слишком много auth-mail-ов'
    USER    = 'USER',    'Слишком много GET-запросов к станицам пользователей. Парсит что-ли? Наехал что-ли?'
    CODE    = 'CODE',    'Слишком много неудачных попыток ввода auth-кодов'
    SEANCE  = 'SEANCE',  'Слишком много неудачных попыток подобрать сеанс'
    BROWSER = 'BROWSER', 'Слишком много неудачных попыток подобрать посетителя'
    ADMIN   = 'ADMIN',   'Слишком много неудачных попыток вломиться в форму логина админку'
    SESSION = 'SESSION', 'Слишком много неудачных попыток подобрать сессию от админки'


td = datetime.timedelta

ACTION_RULES = {
    Actions.GET    : dict(Ip=1000, Browser=1000, User=1000, per=td(minutes=1), rest=[Actions.GET, Actions.POST], for_a=td(minutes=10)),
    Actions.POST   : dict(Ip=1000, Browser=1000, User=1000, per=td(minutes=1), rest=[Actions.GET, Actions.POST], for_a=td(minutes=10)),
    Actions.MAIL   : dict(Ip=1000, Browser=1000, User=1000, per=td(minutes=1), rest=[Actions.GET, Actions.POST], for_a=td(minutes=10)),
    Actions.USER   : dict(Ip=1000, Browser=1000, User=1000, per=td(minutes=1), rest=[Actions.GET, Actions.POST], for_a=td(minutes=10)),
    Actions.CODE   : dict(Ip=1000, Browser=1000, User=1000, per=td(minutes=1), rest=[Actions.GET, Actions.POST], for_a=td(minutes=10)),
    Actions.SEANCE : dict(Ip=1000, Browser=1000, User=1000, per=td(minutes=1), rest=[Actions.GET, Actions.POST], for_a=td(minutes=10)),
    Actions.BROWSER: dict(Ip=1000, Browser=1000, User=1000, per=td(minutes=1), rest=[Actions.GET, Actions.POST], for_a=td(minutes=10)),
    Actions.ADMIN  : dict(Ip=1000, Browser=1000, User=1000, per=td(minutes=1), rest=[Actions.GET, Actions.POST], for_a=td(minutes=10)),
    Actions.SESSION: dict(Ip=1000, Browser=1000, User=1000, per=td(minutes=1), rest=[Actions.GET, Actions.POST], for_a=td(minutes=10)),
}

ACTION_TRIES = {
    Actions.MAIL: ['/api/signup/', '/api/signin/'],
    Actions.USER: ['/api/user/'],
    # Actions.POOPS: ['/api/like/', '/api/dislike/', '/api/subscribe/', '/api/unsubscribe/']
}

ACTION_FAILS = {
    Actions.CODE: ['/api/signup/code/', '/api/signin/code/'],
}


class Acting(models.Model):

    GET = models.IntegerField(default=0)
    POST = models.IntegerField(default=0)
    MAIL = models.IntegerField(default=0)

    USER = models.IntegerField(default=0)

    CODE = models.IntegerField(default=0)
    SEANCE = models.IntegerField(default=0)
    BROWSER = models.IntegerField(default=0)
    ADMIN = models.IntegerField(default=0)
    SESSION = models.IntegerField(default=0)

    # LAST

    last_GET_at = models.DateTimeField(null=True, blank=True)
    last_POST_at = models.DateTimeField(null=True, blank=True)
    last_MAIL_at = models.DateTimeField(null=True, blank=True)

    last_USER_at = models.DateTimeField(null=True, blank=True)

    last_CODE_at = models.DateTimeField(null=True, blank=True)
    last_SEANCE_at = models.DateTimeField(null=True, blank=True)
    last_BROWSER_at = models.DateTimeField(null=True, blank=True)
    last_ADMIN_at = models.DateTimeField(null=True, blank=True)
    last_SESSION_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def increment(self, ACTION):
        """https://stackoverflow.com/a/622676/4117781"""
        with transaction.atomic():
            acting = self.__class__.objects.select_for_update().get(id=self.id)
            setattr(acting, ACTION, getattr(acting, ACTION, 0) + 1)
            setattr(acting, f'last_{ACTION}_at', datetime.datetime.utcnow())
            acting.save()


class Actor(models.Model):

    is_suspicious = models.BooleanField(default=False)
    suspected_at = models.DateTimeField(null=True, blank=True)
    suspicious_reason = models.CharField(max_length=255, choices=Actions.choices, null=True, blank=True)
    suspicious_count = models.IntegerField(default=0)

    class BanReasons(models.TextChoices):
        SPAM   = 'SPAM', 'Spam'
        ABUSE  = 'ABUSE', 'Abuse'
        BAD_IP = 'BAD_IP', 'Bad IP'

    # Бан (пока только ручной)
    is_banned  = models.BooleanField(default=False)
    banned_at  = models.DateTimeField(null=True, blank=True)
    ban_reason = models.CharField(max_length=255, choices=BanReasons.choices, null=True, blank=True)
    ban_count  = models.IntegerField(default=0)

    class Meta:
        abstract = True


class IpActing(Acting):
    class Meta:
        db_table = 'IpActing'


class BrowserActing(Acting):
    class Meta:
        db_table = 'BrowserActing'


class UserActing(Acting):
    class Meta:
        db_table = 'UserActing'


class BadIp(models.Model):
    ip_address = models.CharField(max_length=20, unique=True)
    suspected_count = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(default=datetime.datetime.utcnow)
    updated_at = models.DateTimeField(blank=True, null=True)
    is_not_fair = models.BooleanField(default=False)

    class Meta:
        db_table = 'BadIp'


class Ip(Actor):
    created_at = models.DateTimeField(default=datetime.datetime.utcnow)
    ip_address = models.CharField(max_length=255, unique=True)
    is_routable = models.BooleanField(null=True, blank=True)
    bad_ip = models.OneToOneField('security.BadIp', null=True, blank=True, on_delete=models.PROTECT, related_name='ip')
    acting = models.OneToOneField('security.IpActing', null=True, blank=True, on_delete=models.PROTECT, related_name='acting_ip')

    class Meta:
        db_table = 'Ip'


class Ip_M2M(models.Model):
    created_at = models.DateTimeField(default=datetime.datetime.utcnow)
    ip = models.ForeignKey('security.Ip', null=True, blank=True, on_delete=models.CASCADE)

    class Meta:
        abstract = True
