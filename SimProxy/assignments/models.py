from django.db import models

class Proxy(models.Model):
    ip = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)
    created_at = models.IntegerField(default=0)
    updated_at = models.IntegerField(default=0)
    blocked_at = models.IntegerField(null=True, blank=True)
    capacity = models.IntegerField(default=40)
    location = models.FloatField(default=0.0)

    def __str__(self):
        return self.ip

class User(models.Model):
    ip = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    is_censor_agent = models.BooleanField(default=False)
    known_blocked_proxies = models.IntegerField(default=0)
    created_at = models.IntegerField(default=0)
    updated_at = models.IntegerField(default=0)
    credits = models.FloatField(default=0.0)
    request_count = models.IntegerField(default=0)
    flagged = models.BooleanField(default=False)
    location = models.FloatField(default=0.0)

    def __str__(self):
        return self.ip

class Assignment(models.Model):
    proxy = models.ForeignKey(Proxy, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.IntegerField(default=0)
    updated_at = models.IntegerField(default=0)
    blocked = models.BooleanField(default=False)
    assignment_time = models.IntegerField(null=False, default=0)

    def __str__(self):
        return f"{self.user.ip} → {self.proxy.ip}"

class Block(models.Model):
    proxy = models.ForeignKey(Proxy, on_delete=models.CASCADE)
    net = models.CharField(max_length=32)
    pk = models.CompositePrimaryKey("proxy_id","net", unique=True)
    blocked_at = models.IntegerField(default=0)
