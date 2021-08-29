from django.db import models
from django.contrib.auth.models import AbstractUser
# Create your models here.


# 用户信息
class User(AbstractUser):

    # 手机号
    # unique 为唯一性字段
    mobile = models.CharField(max_length=11, unique=True, blank=False)

    # 头像信息 以年月日保存到avatar
    # upload_to为保存到响应的子目录中
    avatar = models.ImageField(upload_to='avatar/%Y%m%d/', blank=True)

    # 个人简介信息
    user_desc = models.CharField(max_length=500, blank=True)

    # 修改认证的字段为 手机号
    USERNAME_FIELD = 'mobile'

    # 创建超级管理员的需要必须输入的字段(不包括 手机号和密码)
    REQUIRED_FIELDS = ['username', 'email']

    # 内部类 class Meta 用于给 model 定义元数据
    class Meta:
        db_table = 'tb_user'  # 修改默认的表名
        verbose_name = '用户管理'  # admin后台显示
        verbose_name_plural = verbose_name  # admin后台显示

    def __str__(self):
        return self.mobile
