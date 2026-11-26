export default {async rewrites(){return [{source:'/backend/:path*',destination:'http://api:8000/:path*'}]}};
