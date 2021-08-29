from django.shortcuts import render
from django.views import View
from django.http.response import HttpResponseBadRequest
from libs.captcha.captcha import captcha
from django_redis import get_redis_connection
from django.http import HttpResponse
from django.http.response import JsonResponse
from utils.response_code import RETCODE
from random import randint
from libs.yuntongxun.sms import CCP
from users.models import User
from django.db import DatabaseError
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth import login
from django.contrib.auth import authenticate
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from home.models import ArticleCategory, Article
# Create your views here.
import re
import logging
logger = logging.getLogger('django')


# 注册视图
class RegisterView(View):

    def get(self, request):
        return render(request, 'register.html')

    def post(self, request):
        """
        1.接收数据
        2.验证数据
            2.1 参数是否齐全
            2.2 手机号的格式是否正确
            2.3 密码是否符合格式
            2.4 密码和确认密码要一致
            2.5 短信验证码是否和redis中的一致
        3.保存注册信息
        4.返回响应跳转到指定页面
        :param request:
        :return:
        """
        # 1.接收数据
        mobile = request.POST.get('mobile')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')
        smscode = request.POST.get('sms_code')
        # 2.验证数据
        #     2.1 参数是否齐全
        if not all([mobile, password, password2, smscode]):
            return HttpResponseBadRequest('缺少必要的参数')
        #     2.2 手机号的格式是否正确
        if not re.match(r'^1[3-9]\d{9}$', mobile):
            return HttpResponseBadRequest('手机号不符合规则')
        #     2.3 密码是否符合格式
        if not re.match(r'^[0-9A-Za-z]{8,20}$', password):
            return HttpResponseBadRequest('请输入8-20位密码，密码是数字，字母')
        #     2.4 密码和确认密码要一致
        if password != password2:
            return HttpResponseBadRequest('两次密码不一致')
        #     2.5 短信验证码是否和redis中的一致
        redis_conn = get_redis_connection('default')
        redis_sms_code = redis_conn.get('sms:%s' % mobile)
        if redis_sms_code is None:
            return HttpResponseBadRequest('短信验证码已过期')
        if smscode != redis_sms_code.decode():  # # 如果用户输入的 != 验证码
            return HttpResponseBadRequest('短信验证码错误')
        # 3.保存注册信息(数据)
        # create_user 可以使用系统的方法来对密码进行加密
        try:
            user = User.objects.create_user(username=mobile,
                                            mobile=mobile,
                                            password=password)
        except DatabaseError as e:
            logger.error(e)
            return HttpResponseBadRequest('注册失败')

        # 实现状态保持
        login(request, user)

        # 4.返回响应跳转到指定页面
        # 暂时返回一个注册成功的信息，后期再实现跳转到指定页面
        # redirect 是进行重定向
        # reverse 是可以通过 namespace:name 来获取到视图所对应的路由
        # return HttpResponse('注册成功，重定向到首页')

        # 跳转到首页
        response = redirect(reverse('home:index'))
        # 设置cookie信息,方便首页中 用户信息展示的判断和用户信息的展示
        # 登录状态，会话结束后自动过期
        response.set_cookie('is_login', True)
        # 设置用户名有效期 7 天
        response.set_cookie('username', user.username, max_age=7 * 24 * 3600)

        return response


class ImageCodeView(View):
    """
        1.接收前端传递过来的uuid
        2.判断uuid是否获取到
        3.通过调用captcha 来生成图片验证码（图片二进制和图片内容）
        4.将 图片内容保存到redis中
            uuid作为一个key， 图片内容作为一个value 同时我们还需要设置一个实效
        5.返回图片二进制
        :param request:
        :return:
        """
    def get(self, request):
        # 获取前端传递过来的参数
        uuid = request.GET.get('uuid')
        # 判断参数是否为None
        if uuid is None:
            return HttpResponseBadRequest('没有传递uuid')
        # 获取验证码内容和验证码图片二进制数据
        text, image = captcha.generate_captcha()
        # 将图片内容保存到redis中，并设置过期时间
        redis_conn = get_redis_connection('default')
        # key 设置为 uuid
        # seconds  过期秒数  300秒 5分钟过期时间
        # value  text
        redis_conn.setex('img:%s' % uuid, 300, text)
        # 返回图片二进制响应，将生成的图片以content_type为image/jpeg的形式返回给请求
        return HttpResponse(image, content_type='image/jpeg')


class SmsCodeView(View):
    """
    1.接收参数
    2.参数的验证
       2.1 验证参数是否齐全
       2.2 图片验证码的验证
           连接redis，获取redis中的图片验证码
           判断图片验证码是否存在
           如果图片验证码未过期，我们获取到之后就可以删除图片验证码
           比对图片验证码
       3.生成短信验证码
       4.保存短信验证码到redis中
       5.发送短信
       6.返回响应
           :param request:
           :return:
    """
    def get(self, request):
        # 1.接收参数(查询字符串的形式传递过来)
        mobile = request.GET.get('mobile')
        image_code = request.GET.get('image_code')
        uuid = request.GET.get('uuid')

        # 2.校验参数
        # 2.1 验证参数是否齐全
        if not all([mobile, image_code, uuid]):
            return JsonResponse({'code': RETCODE.NECESSARYPARAMERR, 'errmsg': '缺少必传的参数'})
        # 2.2 图片验证码的验证
        # 创建连接到redis的对象
        redis_conn = get_redis_connection('default')
        # 获取redis中的图片验证码
        redis_image_code = redis_conn.get('img:%s' % uuid)
        # 判断图片验证码是否存在
        if redis_image_code is None:
            # 图形验证码过期或者不存在
            return JsonResponse({'code': RETCODE.IMAGECODEERR, 'errmsg': '图形验证码已过期'})
        # 如果图片验证码未过期,我们获取到之后就可以删除图片验证码,
        # 删除图形验证码,避免恶意测试图形验证码
        try:
            redis_conn.delete('img:%s' % uuid)
        except Exception as e:
            logger.error(e)
        # 对比图形验证码,注意大小写的问题,redis的数据是byte类型
        if redis_image_code.decode().lower() != image_code.lower():  # 转小写后比较
            return JsonResponse({'code': RETCODE.IMAGECODEERR, 'errmsg': '图形验证码错误'})
        # 3.生成短信验证码：生成6位数验证码
        sms_code = '%06d' % randint(0, 999999)
        # 为了后期比对方便，我们可以将短信验证码记录到日志中
        logger.info(sms_code)
        # 4.保存短信验证码到redis中，并设置有效期
        redis_conn.setex('sms:%s' % mobile, 300, sms_code)
        # 5.发送短信验证码
        # 参数1  测试手机号
        # 参数2(列表): 您的验证码是{1}，请于{2}分钟内正确输入
        # {1} 短信验证码   {2} 短信验证码的有效期
        # 参数3: 免费开发测试使用的模板ID为1
        CCP().send_template_sms(mobile, [sms_code, 5], 1)

        # 6.返回响应结果
        return JsonResponse({'code': RETCODE.OK, 'errmsg': '发送短信成功'})


class LoginView(View):

    def get(self, request):
        return render(request, 'login.html')

    def post(self, request):
        """
        1.接收参数
        2.参数的验证
           2.1 验证手机号是否符合规则
           2.2 验证密码是否符合规则
        3.用户认证登录
        4.状态的保持
        5.根据用户选择的是否记住登录状态来进行判断
        6.为了首页显示我们需要设置一些cookie信息
        7.返回响应
        :param request:
        :return:
        """
        # 1.接收参数
        mobile = request.POST.get('mobile')
        password = request.POST.get('password')
        remember = request.POST.get('remember')

        # 2.校验参数
        # 2.1 判断手机号是否正确
        if not re.match(r'^1[3-9]\d{9}$', mobile):
            return HttpResponseBadRequest('请输入正确的手机号')

        # 2.2 判断密码是否是8-20个数字
        if not re.match(r'^[0-9A-Za-z]{8,20}$', password):
            return HttpResponseBadRequest('密码最少8位，最长20位')

        # 3.用户认证登录,采用系统自带的认证方法进行认证
        # 如果我们的用户名和密码正确,会返回user
        # 如果我们的用户名或密码不正确,会返回None
        # 默认的认证方法是 针对于 username 字段进行用户名的判断
        # 当前的判断信息是 手机号，所以我们需要修改一下认证字段
        # 我们需要到User模型中进行修改，等测试出现问题的时候，我们再修改
        # 认证字段已经在User模型中的USERNAME_FIELD = 'mobile'修改
        user = authenticate(mobile=mobile, password=password)

        if user is None:
            return HttpResponseBadRequest('用户名或密码错误')

        # 4.实现状态的保持
        login(request, user)

        # 5.根据用户选择的是否记住登录状态来进行判断
        # 6.为了首页显示我们需要设置一些cookie信息
        # 根据next参数来进行页面的跳转
        # 响应登录结果
        # 根据next参数来进行页面的跳转
        next_page = request.GET.get('next')
        if next_page:
            response = redirect(next_page)
        else:
            response = redirect(reverse('home:index'))

        # 设置状态保持的周期
        if remember != 'on':                # 没有记住用户信息
            # 浏览器关闭之后
            # 没有记住用户：浏览器会话结束就过期
            request.session.set_expiry(0)
            # 设置cookie
            response.set_cookie('is_login', True)
            response.set_cookie('username', user.username, max_age=14 * 24 * 3600)
        else:                               # 记住用户信息
            # 记住用户：None表示两周后过期 (默认记住2周)
            request.session.set_expiry(None)
            # 设置cookie
            response.set_cookie('is_login', True, max_age=14 * 24 * 3600)
            response.set_cookie('username', user.username, max_age=14 * 24 * 3600)

        # 7.返回响应
        return response


class LogoutView(View):

    def get(self, request):
        # 1.清理session数据
        logout(request)
        # 2.跳转到首页,退出登录，重定向到登录页
        response = redirect(reverse('home:index'))
        # 3.删除部分cookie数据,退出登录时清除cookie中的登录状态
        response.delete_cookie('is_login')

        return response


class ForgetPasswordView(View):

    def get(self, request):
        return render(request, 'forget_password.html')

    def post(self, request):
        """
        1.接收数据
        2.验证数据
            2.1 判断参数是否齐全
            2.2 手机号是否符合格则
            2.3 判断密码是否符合格则
            2.4 判断确认密码和密码是否一致
            2.5 判断短信验证码是否正确
        3.根据手机号进行用户信息的查询
        4.如果手机号查询出用户信息则进行用户密码的修改
        5.如果手机号没有查询出用户信息，则进行新用户的创建
        6.进行页面跳转，跳转到登录页面
        7.返回响应
        :param request:
        :return:
        """
        # 1.接收数据(参数)
        mobile = request.POST.get('mobile')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')
        smscode = request.POST.get('sms_code')

        # 2.验证数据
        # 2.1 判断参数是否齐全
        if not all([mobile, password, password2, smscode]):
            return HttpResponseBadRequest('缺少必传参数,参数不全')

        # 2.2 断手机号是否符合规则
        if not re.match(r'^1[3-9]\d{9}$', mobile):
            return HttpResponseBadRequest('请输入正确的手机号码')

        # 2.3 判断密码是否符合规则(8-20位数字,字母)
        if not re.match(r'^[0-9A-Za-z]{8,20}$', password):
            return HttpResponseBadRequest('请输入8-20位的密码;数字,字母')

        # 2.4 判断两次密码是否一致
        if password != password2:
            return HttpResponseBadRequest('两次输入的密码不一致')

        # 2.5 判断短信验证码是否正确
        redis_conn = get_redis_connection('default')
        redis_sms_code = redis_conn.get('sms:%s' % mobile)
        if redis_sms_code is None:
            return HttpResponseBadRequest('短信验证码已过期')
        if smscode != redis_sms_code.decode():  # 如果用户输入的 != 验证码
            return HttpResponseBadRequest('短信验证码错误')

        # 3.根据手机号查询用户信息
        try:
            user = User.objects.get(mobile=mobile)
        except User.DoesNotExist:
            # 5.如果手机号没有查询出用户信息,则进行新用户创建
            # 如果该手机号不存在，则注册个新用户
            try:
                User.objects.create_user(username=mobile,
                                         mobile=mobile,
                                         password=password)
            except Exception:
                return HttpResponseBadRequest('修改失败，请稍后再试')
        # 4.如果手机号查询出用户信息,则进行用户密码的修改
        else:
            # 修改用户密码
            user.set_password(password)
            # 注意,保存用户信息
            user.save()

        # 6.进行页面跳转,跳转到登录页面
        response = redirect(reverse('users:login'))

        # 7.返回响应
        return response


class UserCenterView(LoginRequiredMixin, View):
    # LoginRequiredMixin
    # 如果用户未登录的话，则会进行默认的跳转
    # 默认的跳转连接是：accounts/login/?next=xxx
    def get(self, request):
        # 获取登录用户的信息
        user = request.user

        # 组织模板渲染数据,获取用户的信息
        context = {
            'username': user.username,
            'mobile': user.mobile,
            'avatar': user.avatar.url if user.avatar else None,
            'user_desc': user.user_desc
        }
        return render(request, 'center.html', context=context)

    def post(self, request):
        """
           1.接收参数
           2.将参数保存起来
           3.更新cookie中的username信息
           4.刷新当前页面（重定向操作）
           5.返回响应
           :param request:
           :return:
        """
        # 1.接收数据(参数)
        user = request.user
        avatar = request.FILES.get('avatar')
        username = request.POST.get('username', user.username)
        user_desc = request.POST.get('desc', user.user_desc)

        # 2.修改数据库数据,将参数保存起来
        try:
            user.username = username
            user.user_desc = user_desc
            if avatar:
                user.avatar = avatar
            user.save()
        except Exception as e:
            logger.error(e)
            return HttpResponseBadRequest('修改失败，请稍后再试')

        # 3.更新cookie中的username信息
        # 4.返回响应，刷新当前页面(重定向操作)
        response = redirect(reverse('users:center'))
        # 更新cookie信息
        response.set_cookie('username', user.username, max_age=14 * 24 * 3600)

        # 5.返回响应
        return response


class WriteBlogView(LoginRequiredMixin, View):

    def get(self, request):
        # 获取博客分类信息(查询所有分类模型)
        categories = ArticleCategory.objects.all()

        context = {
            'categories': categories
        }
        return render(request, 'write_blog.html', context=context)

    def post(self, request):
        """
            1.接收数据
            2.验证数据
            3.数据入库
            4.跳转到指定页面（暂时首页）
            :param request:
            :return:
        """
        # 1.接收数据
        avatar = request.FILES.get('avatar')
        title = request.POST.get('title')
        category_id = request.POST.get('category')
        tags = request.POST.get('tags')
        sumary = request.POST.get('sumary')
        content = request.POST.get('content')
        user = request.user

        # 2.验证数据
        # 2.1 验证数据(参数)是否齐全
        if not all([avatar, title, category_id, sumary, content]):
            return HttpResponseBadRequest('参数不全')

        # 2.2 判断分类 id
        # 判断文章分类id数据是否正确
        try:
            article_category = ArticleCategory.objects.get(id=category_id)
        except ArticleCategory.DoesNotExist:
            return HttpResponseBadRequest('没有此分类')

        # 3.数据入库
        # 保存到数据库
        try:
            article = Article.objects.create(
                author=user,
                avatar=avatar,
                category=article_category,
                tags=tags,
                title=title,
                sumary=sumary,
                content=content
            )
        except Exception as e:
            logger.error(e)
            return HttpResponseBadRequest('发布失败，请稍后再试')

        # 返回响应，跳转到文章详情页面
        #  4.跳转到指定页面（暂时首页）
        # 暂时先跳转到首页
        return redirect(reverse('home:index'))
