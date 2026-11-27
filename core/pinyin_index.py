"""Zero-dependency full-BMP CJK-to-Pinyin converter for dynamic playable character folder matching.

Data derived from MIT-licensed `mozillazg/pinyin-data` (https://github.com/mozillazg/pinyin-data,
Copyright (c) 2016 mozillazg), covering all 20924 CJK Unified Ideographs in U+4E00..U+9FFF
(Simplified Chinese, Traditional Chinese, and CJK Kanji including polyphones).
"""

from __future__ import annotations

import array
import base64
import re
import zlib
from typing import Dict, List, Optional, Tuple

_START_CP = 0x4E00
_END_CP = 0x9FFF

_VOCAB_B85 = (
    "c-mcES(f8C4*b_ybSc?p+VmoM5!;qdKa2&GYToPa%FeR2Z~+2=0N5?LJLU1*ua`8QyW24JuU!ALl<t+g&t<5;{N<smKXl(=>>pFN"
    "@|U0bi)*eQ?hd8@o9e%%t6zHL`up>cyW?dl^`oW!?<=SNTKZ$@p15SLzbM_I-n3g%cbw{<C;aDwFV%<WKm4yA=u|&?&$!`Iuea2z"
    ";fwvDKFYz5aqi9q&r-T`>d*BP%TVut->(;3_nPZJsryU(Wc}i;;4hDOww}Lu;VF;xwR--t-f+aD<5lZ}4tVkIgaJsnRK5L)AL_1n"
    "qtw?S#LMTt-l_h#zWg}wk8kPbGT}|SNBvkG)<^wksF%$>E?q~mU+Zn^kAFjVuOBI?USaH?^-=WjPYlx&&x>in^Lv!`W5s*xt91fW"
    "Ki1b>_*_5y!*QzjIMopx2ad?lJ?hmS^<sCt@S3}K>3;PRb;j#wIt=571CThD99KLxKYlKF_k<_D^Qr3Xir*;lX7&AYm);m;{8b&e"
    "{#UwN$yitmrwgB}*Ey%L{uS=P`APoaS6>4U@WM#d$6SU!b#r}zIv3}@4(ttop7|fHlL2p4hjPF)B+h2X5#syzPkiW6=Oc3{>zw0<"
    "!-N}QZhKBYmNu7LcdGZsQ$Nz!y%X0y-m5+y7BF9&`=(nH-leYoeypnjyQZ%6y7udY;4iTB>J#D`XRh^r#kBrSb>Qoo<0>6ETJzA?"
    "#lq?0s;N(ahvMqtQkW;L0_?A`$CI8h#~6$gCK3yi&t8AWy;O(e=)KzEJ^r-H>k`CBEf^Lrtg+{OJad1jt9HUrVyoi~1`a3IZhhwZ"
    "7Ckmc-Anb8b(AtLdhWSEpLKWCxvukk!u3z}{eD@WZ<7U+fyWrIk$Nns7gi|0g<-@Bp4-;t|6aI3GIni!sgk{MWm@Vc;2`$c4RrzY"
    "mi4!F3)Y=GRU479=jt9l*R@}5)xgbFKgsdJZ3?Hgd({P8x+90~5R16}e8vC_^)Zw7cKuzC>z^=0Glu)(?SWNPpS`D%D!5=B*=nw^"
    "&8NC-FddnTs;(Vud(1#xkbS*fj~81nu?|nXZsIyvU^BVFW)4$*iWAHktZt82tj}1N+f7Su<od3k!eaRjb>!<iYXC18zzbL7y*`k4"
    "ZrxTIq-r_pSJJy5`LVjf5-)}22#;{0Tfh$kOxnOzGGTjR(c(?&E8S!!-~oDU+k5@DP8{ytC#=*nZSNgpP>mwq8HS@y0ybWCAN4I@"
    "ncxt5F8Deg_5JWe!79ba{;O7~t`gn9J`t@>cTD}7WGu8)@Y9HIUbv8_W;18aJVu=}Usp^uk3G!eT*nFTF=CD2%?_C6r}iY4A3Vg="
    "rMiH6nABUna)C{#|G|Q%tLpDu!G$JU19Y*;!;1Ef<3|4!OeCG=qAR|*>acOREbHFDQ)6oDwR^cj4#Ts)-XU|3^PBax>b}hMb3IpZ"
    "ti^;6)?elNBK1kQd}$c^<IdA!AnPi`E~vA{`SH%;l+kQq_BvjuUXzQzE(UB^dc-4ES)I__!P@q8U9&FXmCiM^YCdeO&a{x&Ua%zH"
    "jUHR5VX&1RGd<dOf*+}?Wa>Wn)IISMFynQguxgJ3HxU2^onrmZ8@A$IY)_7t-MZqG(7a(Tur03i9WY7ny7At1|J7IF+z)d4@=Gv?"
    "^1JxIg^RB9C|x)XQxS?<iGg4Q0FPEa0&h+`QcWbcOBy`|_;fY+SmX5yTIaAAb<Y+~EIe<23uE}<)p?}_S9(ug8`aj<zj|Qn+c<MU"
    "$O+1})M*2_3*!$kSL&OWojJ8pg(c~E>6r$OgC<b1atYS4uTxUL)_-8XhW=B(b%!%(LtZ~wof)=Mdkjn=mMyM>EsPQCyw;XMo<JZ#"
    "gOOuEo)}mz{CklRduWER?Swe%8XmRzhzaWdRr`u9Q~Co|_k_JvEg&}!p6EogAXL?S%cc1mu9cZHZ#&PAeQ2tO?!&Q4T)4nD^qy-S"
    "gqi-H@8ogd?7-4?aw_t!AGpI}2+FH^O9_x@;T7MS({|)53uVI~cX;=@PXs?7wA{3KbsN|B>;!qMi8<9xh*d_{$^F&wz3=$&dkDPL"
    "$)MPC03+Suw_y6-J@8P)a6K2@54UNMdeR=4^y|97t1(Ut3hLgi|I&`)*L6?gNqD`HsG943E*#o!6qfj01S>iFg?^yF2nGRcuhkX9"
    "JJ!Yi)|aaD!j(H>jrzO#|F%tu4g$`k5d6a9VV3}IBea0`lOe92R7R8rjN!&;6i#$z%nbtx2Tw~TNd8E4X!UMW@mlT)@lL?2b-$-D"
    "{_vCa8LETE&HxxV*~Kzi!d57VH?Rt;X{y$U-W%}&XB2P`F;uEg1$YBb4(o~WCKkX14)oqc*VybBSpb|D=A^&Dluq(`N8rvvGwAS-"
    "Xr->3XZ^$zSZ<=%c+qPAS06y3f*j0=lQao$P5ra*^QS`lR^2JrF=8b6pVPouxG6&NASql^@HKDfu5NIIb+i|B_QbRo;R(1h4vY62"
    "zJTzGAg{im%`>KHrPIThz*<aPZ3Mi4xYfC0ZqC|7c#68v0bQ`*>F5DSzWxL2g1GHbZOKGq<Z!~4H(n)-4{d<rTfsmEgczU9i%#51"
    "*!>(k;B0^!0h=cg2o|E>8pvcKG{tnR1Ch0McmEZbPuSgFcNGuxa2s$La3OXd6?W7if|Dv(3aMvUEekRyAlLeLXF4%0rjb6Q4mEr~"
    "9|+Mmj5ZKa5mC^GVFY@r8xQUjPx;|wVR00!4Lz)oL^d2h6mDl)zWM?;nnp~2jbDctaqiT*2C)Ye#*ah_4BzVoHHrXc0N*s$KwpMB"
    "UaY;sc&^*(bcGi$`u&L!iK24HoCFk^F<&(w)zQ+KK8#`cvMX^RW}BM~WC{J(fQP*k!!W4iqWWZpRTZ`LZ~||QvAq@@4#qGU{2gs<"
    "<X977Dh*rF8o1NkAVjD?k^%UHKd_SqMi2r;%s|UnXB41S^IK?lW-POz&IDFN#X;4x^btg6VfShYKq<fzTmsa7Xnq;;WZF>TCwo^A"
    "5ts~cLb0t7>)}NS-&UG%p!#Zpgo^>g>YQ8#4m~2BI(>6-oV94zYC|}#<^y3}!Dde~F!+2?j9M*6muMqqgKta<Y(sysmlLhA^5K?1"
    "-CsWUx9~!+j6nSyU|?JjDZrEjll4dVAAX}wI-VTkp5%u!+#bSnT1FyMQVN0{@|tIuiaH;KW5j`|UTjP~U=<z!W`fs%$L9_lg!p<e"
    "Db+c^Lc%n0P2r36)?8=6EC`W*+2&gd9P?I(5~F*@jp-KFY{CPRgm>Z!InzMabv;y%5e5iew#L_IzAC01Q-vGQfyhS7nczzFE3o@@"
    "Xy$?5xLTMRm|hWb=U_7w5Md&#TSHU}C~RzvJM-ojk3w||JuG&$6b$j|p9<6!VD^j{e~gs*%8&YD^~VQywJkFTfQAMU35+r(^$d5="
    "-zS0{;17@rD;&(A*Tc(TDC(1(>4X&N*13d*q^+RCKFdwfmd^^318T$I_M>?Z?InEUi=eqi$^5R2ND|0;<^Wn3!793Aj19SfFCYRp"
    "Y8@b4q7E~NJiPr0HVaQgZVkp{v<a4{x{#Ag6|8qtpST3I4ehUDvsVN282*2Gf-695)&sA3!V^sWbLzEF1y=~%59Els@GqkJ6b|?J"
    "r=w%UgM13T<iH4xfl**(!>`4V?k8Zn^7C}2FwH$?3o!vFTk$v_T8KhWf~Y&zD2AS|OwT$g46m>h;7q~ZLOvW$P|OVMJRR-D;Ve0k"
    "#*%d71ivZ{S>djKq8;W6k>9}(B&;kr1o(>jd>yPU0>ob|nwYAY<55Oanllk}cF<n0($h{2@<Xd4TP%SYMw;gP%TRO{IL)$Zgl>O|"
    ">HFtk>ymj_qTU+cbcny{W@Q5vp>VO(^>u@7P_)PBC)@;Ku45+dLyg)Oyo}=O35)$(IuQo|W3p;StyqN@M%Xv*FmqVDSl+lcaZA8d"
    "jN;?*Wcbb#L}hr=LYTH136li9GvpTN?Jh>Zb^5t~xYarI#`nB0O^Y1lcZ$_Y%S5x#tlc~)#G>zl8~zk+)NTvN55t}f;^<tNEJ;L~"
    "G<TP}wd$rldp8dN9Q}uMVPbIf(URqJz#9w4BwBkc3qj`-t!0LLCs+$?(IG59!*0@i{vv8dbWEr9sQ6@}p#p>^?}bRF#>{o{4dF9G"
    "n7a{rTe(wEO<wyo0-!HD(yaCj++s2H<h(Z;wax~q+eh7t_|}(kJV+wo?p1F9LT;t8!rr)nhDdF;u6mWCR0s{?YM9z#L-%A3W%;=c"
    "5VF9V^rM31L_~INK@naCED3BJ2pE`Y;A!zvSZbtbNF{;5BZ>MT24ps(aJf&0Ibhpq!iu7J(_-AUv<?rL0WQ^9e*2*K0MQ<ox%_N3"
    "+>gYO!hm@O&1~?Vc-%LMHiP1h9OlUT@E%0GgSjV;>zYW~^t#X3Ct`y$zcwo18o5)Gz<y4O+W=<qgWw6m{TsvKjYoXd|9``60`C$E"
    "(5i?&6xWh<E$8AKZ8pmQj^IR^KqMUCtny2+K1_*-Ea#kZH=LZr`Y1uAfPsTfd-9@NBU-}*UW<U$o5V)4;RU;U@Dy{!KgEI)Oy0y}"
    "l0D&0B^Sjtf*~R&`XWEiv;mzO@Ikf5Pa8Eve4rr;5!ekgH96>kE2;nTA(@f&-z75<7cJMpBTA$4r=%=xIv~{me+;w5g@k8jK9t#;"
    "Q&zlGpA;_s!OX6>q2}|HQ#6VHp#@U9h}V5>8RYe{?LgD51DQTY_&t(%oAJ8^@LLpR`GEoCSCQ&kb{{T!Mx7`6yWC-AifKMHw&p}i"
    "APY`S45<}$)+w3gd9hc;|G*lFAO_N27zk%R5%<nPvG`GO%B8)9h+vW)&el$XHQE>LjpU`T=C~Qk0R3wHa>VI%<jus1))|F=6I<@*"
    "&}!M;-_hbMTBol1#1Q6`Bd<Jh`-+kLL{14y0O<iP%9%k7F@#wYFju5WM=Zgwa~D7j#0zxpbV)z06d2)o<3P11gwO6Y-h}IKVXkZh"
    "$bEC6>nf2?HO#nqG#2eey@^r|f^TBvEJv`b!bAN;LSolH$f&`C^bsx1{F7;OWyl9X4#oiu8QLE+rd|k^_`eH1kz(m{@ZL@q)Ch0X"
    "q7oO`6A=XC1jGI$V=vRN*0lys@I}blznnyX-K}F_E~jzD+8(zc>zS|WH<1R}?Uq;?fVF2EkU|?G_ANV1s22Lay1)_J@EXJ;*U0J5"
    "f{DtQ4r2g8*bhbYUd+vykc8w|jx~INS4T8pb;u(7Lk|t}N)ZUsH?cN;f_9wW#kA2cSRg?k81l6+r5Ngl0N3*%knt$W9y2t+bzri8"
    "B`%*w=Ny%=SEB7g18@}w_8lBERmV6{W6>+b@?xed<u)Kht|;R!q=TQuCCuW>28Tlk!s`pyuoWyc;F(Bo5#Jr*yj%cb8ax7iph-?!"
    "x~E6p<ms_K6vCZ97%6~FMp==q=Xjs(HxY<U$oGx^Aua<vfiqC*K<pX0#)6^a=RqO8r!aqr3bCk0JA027%?fsr<p|946s@!o_H~}<"
    "bYa$4ap^H<0PCFnS8ys<D>_89CnxCSFvm=?Gn~RA*6|T5>THW&!?B|Ri;;9c0%Kqsk)<s-yoxUMa!?**3(np(PNWc~4m@)Y2o)zy"
    "W&a+W^X^SR!=7d3m6(knbgJK2L82-b%EiuM<nKrr93w|0Zu%108JbTJYQ$lq_H?oK1Ah<XhfNC?F$<D^Em;DI@mJbD>y?7B<?J?!"
    "L8+I+ps-jWM9Xy6@PoL9`T$<_gD|)#GRj)kkewW<@rhN*ghHc7>(WgM$hpCuLyWh+jO*W}=;9-AXJ#kvTlzqGYTA}UCynTv!QS!@"
    "m#*cz`8*{JMdB6$wa60Deps~Tobv)FFSZu6m9vFffAS`?a@LA@dATFmb+FKq0M*ACnG->*?JVEbo0%z7;JOca6Pc1jcJ5)OR*Q+x"
    "h~2Rao+OJ2teJNcsk1OPdns-m2=A_PA<WxIqC(0H7WPI3$jE>(;#Xy(skbTuwPNTMwJb%U0k+DmD8?KFhn9wFJ{PG=Zn0`VJ2*$v"
    "<FH-`HPJ_ol28fhd3jmpF!eXe3MMec_m+_b!_6?Gp_8MxxP8oV(<NZ@UkRck`57A>LpI8w|FU9;cMPYV09FVu$m}ovXH@i~Rb+(D"
    "<%Bi5#ILVp#*ZQjNS2D=Pgv25C3Rwue<hMte_X<cY?z*v$3Zj+Sqq^)4Gj_;2O`URK)jBg;1guYAN|OpmGHSl5`c4z_<-BZ&S{4l"
    "&dOrgn+;TGSqU-<!3RV&m&U|qYWypm2}O#T`(}~eP&=@X+`6IafgVlR1X$SoOWw9uY)b{138T0&g>u%U5D4C=c=HqKW+KJ4^*<??"
    "F(&)}BbE7_6s6O|EOrL;Sc%FrAYsA%*-L-DL<U{{<h4WQ)=t5=jt)F&HchfLgu**Lr9WjD@=Q%zLG@b>Vck)4Pgdbzw?=Kt#X3T)"
    "g}w4dWC}nml^h6b<bV<QQ)`wSR;@BkEwmCu{%x-7o&w~Bmf>aniX+)XBB=gBrBlkf6XBU9SpqDd?ebRXy_^QaQamvXHye2>n^*^+"
    "P-?%6qC0+-xc`qic4j|TlXWYjZDkl~p23YVvJeNtb&d=~VOo&e5@2jC!uZl#Ndp956M_hWU;%OjTbXamkT@w`1?#S44!|hj50s6d"
    "HhxxfiJN6oeGaR6X_?D&EaHwC1YG2TyxL%@T98{nLe_zC^U~BuOJhCe5~S%(skN(}6i3Pld>OBM4r!5ce8I8c0(XsrF)FqersmNi"
    "$5|fbTL_B@02Lt2k~!zT>7hGu#?Y)1CSukkfaxXProSmWnG;DiMfUhGGtQiOAdk})IM2<U$0{N&fD8r%a`DoWII7~3PvUhr#$W*G"
    "Nliq0#ifAvEl?)cq%}U0nIIngT#`xAMyH>gM8AkG<rhDjN^ot;AR+@i=!xNh9M*~KyHbt6&9PlJ$&c1_;}auLHZ3W0BoV9fEW*{!"
    "`*cjKa9a6-oL{D!!cspd+C1+ZfbH{H#ttrw?(i)sM1Qd|>DVmbssxbL{s?W>l<oV|*r@MKlSPKUr>I;RIT%UeRwOLe!O8PM0_h%l"
    "yeGLFW|yhPg=WQ88r&Eb_07)A?iQ9oXqfYJ#v<!2qdp~?n0{kSq38ujBHdsTjp<JA!#|QgKg}>R`9<)BsT*aP2<;|otCAC_AtYLv"
    "!m~~Wj5`+6%xHVe#fxXi8xO^7bV2589`piB%dm^T6<tKozVLb$9^iRRDymH2cnKlEvSnIfV5);4MgRx-mzrWh3)Jd&MG?fZ`gEc5"
    "JWTSa7VIKZNJemwlsHvSMGHAw@uT;oiDE(+?u@9NgZ@WxtVeSb4k3fIX>pa#6gZcbSAcn|yeLxaX~LOJh1fz_ci<TzYNB*(4JxxQ"
    "L7^D1>NZlqXu(Kd2a|P1UWS~&Exb+treHs41%-w%e3*|fspG+7&w==LB?-y2(8oVA<uV|IhMfdlVA7Zy92$#Eybe=&@o3HwL`qo&"
    "45*l>P=Il8+UytX%qOxb0)N+rU~m=YedtV*<|m2#Gcn+WxL!1wA0~PmPoo9<7f_Bj$9wYyb~Q0hVD)1Tf$xd0C=%<)jGIG%xAGf+"
    "c5kI+k4SoPYQM^x^Tn{BPmy?}DG2uDkGw}0NywKO6u#Q62<}J9*{KZ!qm#A9GL}w3_91$Ms5pdKxG}(}Q$ImcJqM+u&dTddTLjOL"
    "W7!fCy5UWHudv2qgS03UC$JFYWX~!gMwIYuu!#?1MffNzUM_k;D{14_=7|UxY}`ZRW|Cu}x~5(mDWyp0dRVh~-PzgMY{QZ4kyQ+U"
    "@{x$vPll1!r~M*jtAL!+lCLOh%-JzU4ncQhl8Lt7&D$L!Qjk$Rs+fg|jns`r;sGe38mDSf@*e5ZUo$7?FfKP{=ph<aj@Jorn7=Ef"
    "kVNJT!<6kID5H%S<vVFcO_$iVYEvses0mj!nIy+89g4{DZzrNgHO4AU4O3CE8PB5ntT>cqhMQ4*i$Idp6GbUl1c<g`e~*^y9G#$r"
    "6xEY!B^@ZV{-NBjhR!0fwpx`d(sE~gK+nkJN%J8g`IGvZ6xw)bamTP=T4!n8=`8?1$FM_h>Arpv&Ap@x6coP36h$FSK&F=BT{nF*"
    "pRPv1^i7)TNwpADm|Kq58XM0Hko03g0L`orb6v`{IUULbGebNJKZv!JE4YR3T6s^T;TB5C5dJ*rArEqtC+2)H{sUP<5{Er=8ef11"
    "Dh05(u698479W`90t!L~&}1q-A{6oiE%;s4Bd~e68kLQM#HaEJOvjSf7_36JJbSZD2DZ%9GR5t$$XLt{k5`p7a-~y?ShPo=-WN0M"
    "GLng@G6AE^IXU^s#H^~Yi)lH=%BS2af((W~VoE0^8;jJWA%Ic&60);+3dEf!+mXnuzz8mM!RJ<bG*2a1xt4Sj6{%pyONK(0R`I|{"
    "`>$#GrQ_kQR!F{O4jI2Qc~n4{eUz*rqy4k06jHZhU1V@l*&4H>IgDQn_@e4o1^pzs8S^|RVLOQevCt|0noPS<HX`-PDEshJNXa?d"
    "SH@mlzZCZ8R3xVQ1u{4p>9Z)HE&Q{!dGMdg(@aFFAu>{Ok=T`5nAC;AI(n;%o{C~T>Ma1_-$guY$}%b6!4-nRW#JwOy>DC%3gA4o"
    "aGz^2d#Cv2(Pr<FTu#tiLsBHCc1S`Jm*P@pFllU;A*gyq9>m++$qyGaVD5m)uBHZe!JZ1k20|S3ZbK*S3HX8ZmO<Tw+@~BUhTl0$"
    "U(?pNvRu8>CyLc5AA01ref25XQws?iOVPMG#!jAElK_Z5zEaG6H`<KLU!~RDMzHQ9#Ri0S+Ec%#LAa4#nO)VWLPC+Bi^O${FvXo~"
    "@<^X0fx<Z+ZHYikJZ;o8S06%U2<tLbAyIZU&!NH+C{T(X3F;DI2zJWJe&AbJzt-X!*-@roT(sN8)t??Z@~>@nO&{A$f>Y$Uk?SFO"
    "h4KFo6~Y}58(?uC(imiZzyRU!>>8s*`7h~HG5a^>5x6noQQ#tyC67!tL?)ARC`oGgg*hv$AnDv9i!4oNZrWv<kOMSls*c+H8s#^{"
    "A!jlB*H&S8Db5~kvBW1B_^1H7bN<1x5L27ubj(GHNJTYDDnb=-k|8EicgFajEV|_zZS0kY5g&URT9GS&mrARJ!dfw(`OQD-<xr<W"
    "%uRHK3c3=aOK#C9;cRq(;yA?~*#rhl3RV5cn0biIc%TTYyrj~ScE8*5c9$ZFC`>T{;Gaw3k!orceG8?Q2H69BB#T0A>3YdN4aSo!"
    "MbXc2220r`Ll|sngK|UYVJLmyO8FWSFQH<hc?bH^9!^^|CT+$hG9<um!c1wTVGPfu(cdlpBPj$G;U{6bOhzzfGF<&xZ;3fEZ~1Md"
    "6lPs^^>6BNzyRqkgEDXO%DX+6%lcsMoCUszkuOTcJ&JNx0z;x|c^5f`^j5)<6fbY1_jio(bt|za5E6}-_qBjppe15&>$U>ahC$ys"
    "qkb<+B{jl3D^G<tdBx6~TTE#}P&M4j98NCLX*wAT%4hLoAIZsE)!ztNdl#rwb*@T)?6_*H(M>fVDxnlU1rVey3|k-%aZwa(O*i=F"
    "UpA&t`Qg?qAyyPN(n^_I(<L+%x+uvensKl8Cjp<~Z+^0!md{GgimGrFzhaFgnn{<4vaBE=p%i>l$K9I#BM{5Ui~W`&qM>XI<r>!P"
    "^)KzvpOukBdLKSW(=p$()y`N}9|3KN;3g&-5;J_%Bd|D?a+!r9sYQ9-iz}~~WaiE?iD13N=MrJ)VCo`wuIfjTPND65L~(qv6eIUh"
    "VlLL439E2PH{^Oe>-sH8%m-`#Bb_fW$<6eplYb<Y++fkmLW#m^BBV}uMUQx3vl3S!IUD{75=v=NP=yvmv-1lfpV5_T8)yhrLGxAM"
    "F<ZK{(+<8O>wD%0FKz|G4fkd^;&jPhX(`R)Ru{uuNF?lk6qMRpjDDsU3pywtrD`W{4u*o{Q>1!vD;f4zre<3LD<HCmMaxK}A=&ch"
    "U}KK5fls7cRz(7rV$aXLvTOX21t3$SMKRp0=Tpq7)P+N7Ni><4U|166RJ6?xcJ)}rg}`{zPEU%2a=4K{QMzz%v`8%U!wUi&B-h|8"
    "hm0jk_!K!T4lg5m3o&`^`>w(pX6DIUsKBDP0U)Y!5`{zzx13lEIB;SSN=-<%uDSCEtPfH4vrtLqpmW}uRCFP;3uRch_YrpMOg<UO"
    "Jj6R<K`T$D^k9g~jwKv$mJ>YDCZXml|6eZ!7-9J1GqL8yg(%o|9AZ^25SnKJx1x~<H6+Xr+%kc{JM9Z!)HR~F=$~74i9*O$I6-*F"
    "4YP`@I2WZax!(R%FUMM!S&r7bQ3;7G!jwE7Lkv50jVJcsrF7?rCKdyy4SrcCrQI=zJZh-T@%nyks3XeBZ#XmAA993PCxaAPQbLS_"
    "0x{8#7S>#fia>8=*VTY!4l9>vE8K<+`j)ofMWEt0KiA7Jj?~URw`C^13!GH%hCG@o-`1qH=h+7T5nA~*$gfx4R4>ke&cb$mD?V(U"
    "NzV4-3hkVR)kd48T8?xgUI|Iq&0OwOQ|JET1TvM;gCje-X)nxQQ2f1HUyVZ8H`hj^5KvIM70M&LmT-&ZUP^@15z}aCeNvQUhMnmW"
    "8WK>Ao8s@e)42xhy||L>7kXLOEL!ZlE9nBTSz19V6J`c7_okMgBmEjROYlUE%N0SrTGK{LH4oHb?vbk(Yfujt1_aY4r;+jf_e1w+"
    "|6)_ygLq}d_#*8Xn{qWAYnF%wE(|h0J7)BkB@6Le%;IIaXigzt%9>?Ig9wYkZL5?fu<9o3*wC)lkWsR%1WQ1A>7h-BnCNnw05yZF"
    "|4wBigf6Oq3>$R$za|!agT8IiA@KOHdrD}6CM!}9l8=%ofqW&tg<dn{`g5>Ct>oE+?0su!BJNsYITQw~tE9I6MKTWZPB21CZq*eh"
    "!KDoYJfp!tGD!w_hlf5DOI*Hc(Lie@#&(DpdUff|hg7Zl&=LN8)J&!S$<s;+E(X^IoRb}*S4{M)1hr4@DQ&=P0QCEF&6|(_2?nnk"
    "48uY?DX7txQUcs;VV&7h;*V?2#i>NgY8oZ@;yC9Q9tG1^-~F9vLkZj({k}BWo;AtH!M0?k<H2ww)^fk(*k)2nZd#^P*U;+8!j=3Q"
    ";86*+<DSTJQ6}3Ez-MoSokK%tBQ<H~NL;&kNv$IArlR(syh69^m2xMf`UHQz5z8Fn4@uO_HY*|i8GALwqg8tE_Db8>ue{lIzI<x@"
    "HuW{_Gr}HZVtYoH(s8YhHU;~p*g^slCJ3h}8?-n9+JJ%IzU_b#KNDf%;(XAqky3c}0b#dPbWe{IRdJ!38v-M?hH;GalPE<+He6y8"
    "tGM9O){yWXotI$#WLDOHPF>4v{S=D9`n@HDZ*l&CtUJSTnx?-Y>Yt;AL0T<1eC3+5MX$e>JaR3ns0QK@lw)1QJ@jlSB5+Vxa>8Bw"
    "urNmtcTvxcKJp3oCXplH%$<uykZ3VitA>&&xS~RLt6R!D4J)@zYfy*H#|CeNoCj0i+?qzD`<6tV+9$+>%Y5?^N~iubWu_O1;+DxB"
    "+_bfY)tNBvHqr=dB`L?v=4^J`EfB>DwFaCK+!DK%{_kJ`*~5F0MtZSCluq5+h~K6-mup(&*jHx7?_#ah`Xhy{QY`?O-V(F?Rj)Qv"
    "itbNk1AR8ER41r-L@A}$R@=L)5LVX}_D&MuSxxgQQ!{zh-5D4%cGd-2A=5*3B3b2D9#vBaD*sg6N<wF4bB<6WM|Vhs(A9XNdL55="
    "Ev+k-7|*38{13_#%M?y!2f{Qo#904dd^G3iSr+O>HG^_DILbVoP)us-qCyZ=_jv>U$tnms_D^NDmoWMy1uUeH=mSx@m8~PfZ5Fvi"
    "(FZ=oE;b-u*~miqfory44@98b+eq3)1f3dPN8>Lhe-8Pt`jEo&Jv|F^X#sAEBn$hvSWLjkOtY0bsyQi}nCww9A*B)+(!K1t>wD?q"
    "neQRP=<KcULB_K!-(ZKI_*Rjth7o!>t$)qNlLysl2O0Q{W+Su(rIP|K?~)sc&?lN}GlMK`87K^N5x483)W7B|nhF19(G&xNT^%In"
    "`&UA}%@H_l9RIiV(wSQjf{^JHAswpde3id6Zlt=3KEg&@p1oB(X<TV5ljL`V8(<9;z{GusRhZ>98VfpuxBVz$qK*9W$&=Hvt`ndq"
    "TwLMhW<rsgV7nM!@6*(A;uvLYhDfNutQBWKG%z0*L&Ot&#eS}+3ZfOiTBvp-K}VU$HSg3~>S&rnJ+#$a$ptHE&+0F$oh1qBR1*uM"
    "FOi^Yuf9p-r3z54IWl_5k<hOQ#(k&O-ASbbatMUBQBv%<UI7sFTLv~u-U{_jN<Ao-b0Lj+Q#aLfBy?K$5~?_HAv+H05f{<GV6{Ry"
    "s>+!glX8}V3++S)HKripxo-a_^S-3W5~+ul@_KjYXI-G(yWv<X+zfog*zeZrTsJWvpf~edf(nPA$ynA<%?7!<dlr=<cpGh>$!kWb"
    "-x{L4yCq9S*GBwArys@2Q^?GfBu}X6;4WpH$=a4#BB>ke#A4PhnIdhTSm=6Y3eCMfca>Rlnf!c%dJV~-o^s3W-?r{N&*<d9l`KIl"
    "cdGjgNp03KC?8tcO;mTrRX)_sZc427Bc|$*LWQvwt3{nAJYHNv$_g7B=Vc?Cmqw!g)00tEB9Xg5-7Bpqdugi}J|_p(PZ>f!&aRuL"
    "Yu%(QS(6o^dIsuoL%erW->QT9q}okvRgBU`AxHYl#(qJ0sa}!HJs&{DBl3Vw5?ZX@lw-*yucXR@UdC!@ny+;O{8y6KdMCW^Ay7C&"
    "-gk<Smr2Ot5Zh(rD7$5Q_9+sx$E~qLlMr2fMal2(N<9foMOVei?JOtJKbFTbc%T)&X&*~Hg@nn8iVRrNm)rp9=`p#nb|1as4Rlx="
    "XW1FQo0x#*W_vT@?X8Lg)e74tl7kwiQRSHK`J9B)Vdz}<a*c|o&laERDK>C+l=N84Buk5>k1eg2FCECBta|IotcGoy`ptIoV`-^^"
    ">ycXBF%V+Zx5^F+SShv+HK+$zb9LIJI+qA%@dEegjzf6f%A>RxbhV+CkhIR2G857EZf#)o)3S$Ww}5c-Wfsz}A<f$=r>QBA(vc{;"
    "S!K>T(v-x159?><VQS4{jYy+8cyQ}@wjnxaPAY4%_9_(7(MnB%b#dT`XIwqz#+@wfqfdS)!S-;I=l-fzW>=Ad8hHS=Hk2w-TbKz~"
    "Xveb*rXBOmbd<n&c25okv4dj8zvf<6ErQFi^<-f5_X&yB7S(XIw~~Ff=Vj>E--6>iC--g^LmN>j3FbjO>Ye2}rVI{&n#K5@lUvXY"
    "yY}LzR^QV*r#5t(a<jFO4VA$r5x#6W3I~Pf2GZwA9M4B3_k()R&T7D}4^wfyx~{Hl1p%!Gwevd6XlO}iCo;rCQOj+HlT5I+GA%Wx"
    "3M%zc(h&%ZF71p4_7!lQ>Bp(v_PpKJ1_U(D6lVqqD&h+oBrSPHU%So<A^D-8n1Pod{wE|G1djlHqG58gyE3g!;1xua!J7h=w`q4X"
    "aF485=S(HB?i-RRlXfZz+eYd~cHyZ5M3kF8N{&758WQ&(_uK@VGN@Z_@gfp~l-;YU2`$<!1+^m4N-^%Or~!{M2!jf(Mm4W+Tbm)e"
    "2HISa`*2Lr(s4@|Gn?~C8i?Gqe4FlOiB>3Wb>6+TFVRZpIW-Z!ExLC7J*x>LstULfg?MO7!HKiPm;DU*2mk-Ht%%o7i=N!T`7D`Q"
    "Qa@f5-x2S8hu$Ue(Iq>x8=hFQ*-fL)>PpPy{ZkzrBtv$^z?kJ$-r|l>4#ue(MePA-pIk1WK2<Is{Y#OoR))QwBNe5VlR=va)-FbK"
    "i+AdeXy}mJ0y_<UQYy8@0{(e9Kg~l%1NMJo%2y~I+~dy0TP$7puZ!l7JaDFC%Z!oa$e{X^pS8g$wxAj-O=>7nS8VhJxyGKlw#We{"
    "0Dz8-6AN8Z7$PrUlnZ;u>r8^H&d^u_A;y^uYU`3z2yJw!<9jU2d%EMFx*dnNLR9%rTdv$2GjpThbyyM3(?g)(JLPCY!iaz=KJKT9"
    "twrjxT#Xz?5@VOv#%px5NO+-pQCs)3;ezhhN*FM4_p+z5`sm>=N+W9f)fbb{KHBA<8vkAz`J@_pZs(6<?AFZ4ZLO~A?QmyDH@r<X"
    "zuIrgy^cN)XWzkZYy{~P?gY-~kzF?zO`5Vbgp7q3^-#~|)%TLJPOPxchSBmQU3R84T>1L&J&fL>kA5o^2-^G5ShwH?rsxeo^W_xx"
    "I_-My{8P~?{I5QC(N5HIs4S@>xl>~0mYAkVdRvF@VwtV1t&pHH1DbVtf`UiOK!~_fI;U&W8_v~N`}xnI?OBx*YE!sMfuIUZM;I!0"
    "nWA~FiKKYdyT}w43r4XfSETZ`QcL6NWMaEk$YSA5@o_!SH*+8ld`q7d!KgtIA~2{%%Svx-z~J!VfSj)omq~@RNC%GjHE%1fbHQxx"
    "T0UuFH<z1w37#TFEuwQ9Q&-#O?F^Tln;wN4)q{wK=cuWJ3)+c$W=7-=>gk#VA-mwkq(|--Wx0u9*r|8jT4jG+a`ceZZPFJ7`HSTw"
    "SRdzrcT2-^^v6iwyd@{wx=!ko%&_Qykv|mzbUuMV9N2eT0cwU7I^(0?Q86a`+B>=zp=`7C?)md-I__C>!125oB5TPp6>!bb#XWlB"
    "#sNlJnLh2LMFB85e<dmacI5`5G@aWRh^}w8l~&xl-A2of>iK+Zl@Gv3ZvD146%tRdDF*+q+*Hv6ZD(RUgok|-kFP-js&-@z5qZq!"
    "5~xch>mnNs@jJVxvK@t`syV#A!113Wo4Evw;j?chMk@v+cOEBqV(_aSa#X$P>b8*7J?w)+e(k8r9wB#$Esu^cuEpIB7u$dCc{h%9"
    "R@U7|VGBUt%(f_;KxSxR)zz-X`k6SYMdt>XJrP}_^{Tups<Xf3fqiqGT=k5OdI2|YI=ZEAt%=I;kN90@y7fH4t3Ud1ExX6dR(HSZ"
    "{i6ebp!2k4gxd)Zu4nae7VhRUbcXS>7F~6s$xZOo0ff5O9dvK)5AH+LA;pO{o`22KA*;5~y~lXZYiS;ynbc&D#6Ij1Ga7YXTErX;"
    "z|qxtubR)U2y16|m2B;26f+K!3SqYPC$Y^JSE?<pzIn$*)JZ>N!%L`Ff%1s$ZcMVXnC4fyR~#|~X>rd3xa9uMldIQ9y*b0gh<%-g"
    "(>YX3#YfBLgNW=Gr-nxm7DID||8IjE)=N%}a+#bhmI5OAJOQ!KK<y(@r$8l`M2#gmDMn!~7U!)N6@|QtnoMB;18WHCB^|EwaY=yo"
    "ZFr_Z<w=W=dC8WiviM65QaZq2oRBj+IvgE;?o>^B!+%brAaaT)jV9ycCX{;*?lPI&(#smB#9|`pU?S@9p-)3}A5vgfSZpO+E2ZkO"
    "L^m~T!AEji$*3qX@js}!CbU#Me@#tE5$UL4DY<cHoVh`AkHT+}-qDgz=|9nAtxcskLmlyUWjG<Wcj^LOERo`Ndnan(w=-KJq|hG8"
    "HUMflt>y_IQ6D}uO)0PwV;*H~qh=&(4dXyi#}zIv6b$N^+?tg0h-J}ghTXt)R~E;s{<(USAADI^{})AmKNUJWeHvu1<``OaMB?<L"
    "Mb#<+SYf*FI*dU)lzT~wK@hK@<eaL>Raka{P3)tIu6q0_hl=e$(m6}@BokFECs~;5a)pPhNVAW=Vnoxa(jgS1y;Jn5+sX<(+|lv$"
    "=q~H{6AX#Zr`RbBQ{Re{b^a0|vLjtOEm)H-WjzbqLAC}Gjzm7{UzxJHd+waPVr$J58ZAUEw?!puut~J-0a%B=)pN0#oa^A!jm|R9"
    "K|&g_ix>sJ71?I>U|Nz6Y_VcUyxdcPyTd?|8!EbM0`i^4QgkH9*;n3L;Bgp!-Z4yRS{SCRFT^eiKwR7?(eb2XTM#1=+Ndqfrb5)o"
    "o+bLYwt79bg^q%I^lVb6(sfhVtQ%_|`5qdyQ62Qj$hx<vTI4Oc6*x7a>NcZY%G(6O6y8-r(weN@?KTOEqEW-5Q<g}j9kMO`Qd}Cs"
    "ASt9OGHO~|U~eb3v=%7wk+^ZZM3GXA6(iJmspJ9B;J~No)r6a^pz)w;97`RrqTzw=2pWA<ft;s*+UgQwT-Zi*-i4fsq8B&4Zgi_S"
    "e)SJy_c84&57g4yVdNmkFILF9IKwQm`j#OSR?}y!`*~=JnrP@|B008^Szx&BE9<6@TUj~}nce+zJM1pF=vHQ@z9E4#n{1MM0#dcX"
    "z1^Iu95>~B6F5Dk4Gh~88u>9AZnPJab6`DNoEml-+Q~33wvF@o)Q-npeLhVe73XKEE>V39H!8nn3g%X4z*9S2G$YoCT)GlnxRa!W"
    "7j>awcbXzJbaXG=Q{$#*p9}Mn5|1pMyR`UN6A1-<bP<fxaZr{#@?C1+Cn0TnD3?Rd`(7`4?MSFuoW=5Eu$?>~1D18n|2RR6Cl7+~"
    "p=wXduoda5UL<OjRI_3&anWH30&`b4AMfq+S~t97qyXpaDrudA<5nXy=5bb}>!YsH?y8x_U>~;E=WSX{7a3yRs!CM>RdU}>RyGC5"
    "j?J^gAwJ2C2;0dHp+vv)jG<*{?8M0Q$VnyQi!1z0ZuTN5!)#hsuH|_Xi)l#=P7)Y;0ri<NS36yj#AKTollKob_g%6q*dfl1Z70Zb"
    "tGIHKheEMM<scc<zW3#2SK8|Sq#7FzLzYKVMb~%m!5~Bc&M}81L`EO(>sHjO*{!D)15P^L$_+T+PbCJ_i4VNfank|5ETjIET^}6l"
    "copt?ZL*Aa&^cVM5J{Qh)b^2>s{dT#0Fl-MK@MNxp9{=BTWykzAvlIMEI*f*CaL0-G$M)cYl<1Q=k9qrWO6HV&MnR}D~imL%(KAj"
    "B~q3;;fSXextsD<=|v=S^;x+dDh9aHD;GhV?GRGx9BCjZN-QCjx<&VrVYKppa_fkwVzk!u<l|1*D+>;iIY3nKNSDt;kwZQZ$F3H&"
    "j81u@n}*OS9k*s8acKEYan6+u5>RQ<txU)}c`94wMI`oFK_Tz2Ox@j}^gOtTI!^4xPFw_5a0UYjVqMv2Yhf=Q#ogT8tw6c8CUks$"
    "phVN{`hIrdQD!X5)mjD;8k}?r-ZSd}JD(>u=wuw8e>_|1*BYo2a!1=aL+_bqDSc!&SM4Elz(3bHH*UZOi2(unFymh|F$-lt2(yXE"
    "Zz)b5wTy^F0Z$!k$4XcM^U-l_rF9B6BDpucROeEKL1)-*{fno~%nEe88iP8U67AetD9&S_oKHW|c!X$(3reCO1H)qp7$F6u;u}r3"
    "G|Su4YrSRAC3V&@g|uEgI;Ci!P!ag&MkY6DIwXPWo{d6}Xh2NPAPta0+|fJ0EnnQhh&BBC{H*dQQl9G6EIA>Qi$5jqe4<tJ<@dHN"
    "yhL=J(FavyiWnN}P*n1xj8$gkl_njdaA)tBXlkbYdUC5MmK3lXGO34pVRtQFO9*w`A>*UhSGGU$7j9<E9rB6yMHXE>Olf!K+%o5E"
    "pSrdarG)rYsOAII2Q%YiR{EYK{6m?IILJ*aFhsJVU4CwBFhql|-Br6dV7?o+L!o{-8rZ6bv+GrqFg|3rnT>KDpS*+v)DDf)*P(jO"
    "*s96Ev^(b5o!^p<Zya}jsio_qs2$rA>Yd~?LW;&lI{U5$q$yz^qF4G?$r)FdZ(V`5!-FE9t!4P$BymDRr?x;DO7k+ijwYe~bXl}s"
    "?PNawXVr{O-%`WO)aYCyf@wR;W?)a2Gcb{R1}tp(<?ZvaDmgj_OYEZ_&+dVgs8C@h&Ed;APSJYm%j+c`s|AvG;kCub*r;U66%d%d"
    "S4l2+n4-8>zqqxdN`u9hPt@)_7adQ99YWX6gs+Om39(%j<>o+$hB!gd>O@30F^~6*r0hCT=_$7To}&|$&$3f1P<-h=g~NN~Rw(e0"
    "0EA}<v_ZIS{%RiLkWZ}eGtLCU?<hlet@*(@K&ziVyB(sY?~!e4p;_n=;>gGpVK3{K4i2&lWiJf#U7GY4hij!!qepd|jkogFpLR$*"
    "4lt0Q!;AXsqk0cJ75}LS1?j|3mRO|T8W8MZ))Tn<s?KUu0q0WMi4pBs&84}LYlD358S54WIkq%2fGj}_{zCZ~iamV@gdd{S3AR=z"
    "CNdR)!q8&k*|UmK8@mA&3Xf>3z17W6sn~IHWUF#8wRoJTIJ|;=2$1Maaa<vBb8-tOW#vYl;uWnie%W26_<A=({`DVhjDi$Mk1((|"
    "H$OY8d1@TvVkS}jnVQysE?Gt|IvgXtuak<@HtaN5M15ykcj(kgYz`XkH2D;UD+}B7c+b{!&rL)Xi~uGD>t#={Wv8#|prakdtQAJ%"
    "O9Sl;^sM7*-Dp?=tDkO*b$NBO?=OMAgA_PhuS`xfcJq6(xu8X>Ch_L<!R#jMDvj28H<N~`b!w!u(}W^EfqErdo;do<iqsTL=n+eT"
    "X6Bi{SrJ5>6eW>7<K`c!d~3p$oYxjVi*~&lTdliP1rakdASuj4JU}nHQG58(u&6up2{W(TDP7PBvbS?qw@s?cPi_XRf^(fJ9A@no"
    "t(Lw~Qx}MAwjC1eX2MpW<(KzoV$baao=@a*wo`^QIpo<1ipIT=ls?1VYl!AgEny$+VHTN^bM*h(INyirVLYxg2g=b?pLQKZ-7Sf_"
    "ki=M!O|#WPjLl|DVdZwf;i_IYkD?5$>sWXL@&V&k94@xEy;T>26v-J@F<orl7QJNATi0#ra-22jaFc}K?w}T<uB8Fm)}%G<8&NDK"
    "ouU;D>k3^0p-L*3eQi?LhtOQCJcw{yfR)u)B~!<ELvhC?Qpa1>o=v|yB9p|qD(`%Yt|lzHDWeXAa?fNVVF|ElCLTK90}3Mdnz&Cs"
    "a`2X-52V_AS_MJ55?=0q0sLv6"
)

_IDX_B85 = (
    "c-kbK37n7h_Q%ipexF@4k#%I5vQvzu8Kb5mgi<qOU#FW$_HI{2mJFiE(n7Y9G+IPi%W@@zE@5tal1o?W7Ez?@#{d2O{a-&b=J)$O"
    "&-Xdsb3W&DKIeJ9&!b|*iYLAV5=tboB&om4$Q6<%>2jr%<yB6ulJZi4S4F8Lm8FVgNL9I7s`0)$ziaTjrew-Ba;?;o+EPdAN<FDB"
    "4WywolI!GpX)H}7OPWeEX)Z1J>jue|9BC=J(n@ZWn<S6@YRS!Vizu&KdEZ*v$ZgVA+DUu4T{`ftqjZux<WA|#7I(3=CwEJ}6kua5"
    "EN&x((gh3aOIPW}*cGHZpY@QQ(o1?vAMDGOzS2+nOA#~6l6&MYa<2^FeNU`YxlablAh}-#v*!acM25;R8P1j?7{$Y$k<56MJScx<"
    "b`SCMHyMqW9+pSsQ5hp+<uS$>C*x%T{wZMViTK3*Us)cPNqDGOCd(9=Do@BXUiEoRXOAcO`ze_rGv#TSCA0BREOTToUVcWNmFI}Y"
    "^ZY$e=3~_he3vT=crBDgvY0)W$cyq4qc4@0WtqGp%jH#m6dOwTc7?nquge=m;!Rn}4BnDevYLp@leancJF-UB@|`E^WW8*VjclRv"
    "uDr+ZO|qGHTR7TnvQ_?0?3?rVHhG_UY?lx4$`1UJ5Xqgg3tub&Gt05`L)k5RQt{o3l^@AJWS{KkRV*LN0XZm#q*VSXpU9{3nS9Qu"
    "ici15<6p{GMCxnyJ1pPG5&2e*%D=ELOOA2G<MN&STTbx#_i|ExkRRngeEyUCj1Ts6oKtdIe!+$saz@TFn_uNOIfw7hv*+*3-~xE~"
    "125K>|6=_BxhVgWKRJTp(@R)%SwvNhT2<`!)Ym{e^IfQs9$?g16D^}dnBNterhA!Vx*lTh-g2b|%wVaM)pB~3me&f}K`Lq`{aGsO"
    "96VS>GqkE+t;firYFbuvq`FSzh&6PQ)YMG9Mz7U0FkDM(YelKUk?U%n)WeQksjm&Rp=L9;MtYrIuL(12thsERElspNGtJVb9KV@1"
    "XN)z{Ld!CZnsNjCSgk7Ae4fjEb0kx9G+SG0uC~$}wT|4RdF-)AZq{4$R%Tv_{AsOi^agDvw`p5#r-P)u-mV?Aken)!j@n7@lRNa1"
    "+^L<linanXcWHmQTN{uO%Ozh67^P6VuxE~R)o%Jc+1_1yXix2>jWok$AoI$RKH3*c`e|h>?JNE9Q;~Keay8{1{fpkK1N1&^0lF&5"
    "Kpn(i_cNb{GFVqiZGAv@$q>k44Y5zdi+MU!hiPjat|Qp02J<~2BlRer8-+CwYC7>&khfd@st*yFzv*awn0(FChxHLGe^kflav7_S"
    "={RkSA9H2APQZ5`f$WL;xK7ey-6oUSGGC_XRDD9H=}<7AN8F}!+$XgNeBFkvPw7&b!M6KkCR;qMvvjuZkU2URe>|hl>T|l2IrY=$"
    ")t7lX5{&hQYh&g=pV_>i3y8-;@G?af>0(_1qL*k9UVBjsIPyzi=vrN>FKfOm!(v}wQBRiZtN5orxnH6y^fi4Q{MC{-n9~Az6EuyL"
    "mHL)8=KFn&*O*UN>1zBwN8Sdb<?-qva{L{Twni)KTK->$W$U#f@fj)`*uO7x+Nd)%*52~2z6Yu|>1M24B3p>%&$3nb6Z^k2*Rr}z"
    "&&vBCY&)K>N-QR8fBgVo?!d;Kj5khp>4&<TPkOM;)1auP?9r~Wmytf=lkxfw-KYEYW9;<xfF9)Mkd`vrA@WcCL_gKf7`G;`3L;p#"
    "1g0OO-N~dbydOzM48zLl^0{7wb-&Q2WayXpE0j(86*z7Wb}Px(pz}*PjE|0kmT%PIqdvA}FwznI7Av~TQT>-5!{f(whJL5+n?v$%"
    "Jps1T;e!eKy%xh3&S%Q|3gpQatp~El>q-3qf9Ha@kc`T}XGir%{g1YhePmA?*@pLf=}+Y3YGV7dp3>9!`WNtbhM9WA=`8s&68rn>"
    "2DmbV%9ITc{i>Up-*0+>?{~m9Q;A_?UO$7&bIf5y>eUb%hQg!`;eO>94XK(9<vba3o=p86zPNyQD{`bih(~>V7~-A(>P3##QC&rv"
    "hhP4u&Le_<|75F6jNTlEybLeghYe!X7&8+e&Ep6|;oS}3bG06%iu|P3G@#ylCY#T!8AnvUQ{QxC+rWfoDv?x;Ol%TU#$3U+17P3*"
    "SU8m<4r1PEriaeNkLl)0zAtO0!VvR_K{lUcvqdW{$EY5k^}>Q?AiKU?Wy+fhrlQHl(n_W#KG+UNWNT$p#pH4P4CCGnlB(uvQ_WOo"
    "{~D$yqh*>YWZVyWjropjxKFM%Bee<nmqTV4GeEB4C!0ODNi9>KztsKcIH_&wuy+=|s6!R0YtpqFEZ;*;kr(w$eWOISf%ynOoRWq{"
    "*|HJaUuTx-GT8A4aQ6#re7)HQtDMrtrh**Q>r4|f2~6yjEOQ#RPv^7U(uE94^f0;B)HE~aVY3WrZVnKe7L2=FZeV8TB-<pKW1Qw`"
    "X>v^~bCIg&l*|hDztQ9ny<)7}&8sZAw~H*iNZq)}jDYda$_dRgH=9e~;z~5sEv5?leyo}7cdHqM8mX<VO)i-<hON`Jjk(R_X<O6I"
    "6u>kp?aeB^ou3Y-4eIL@#~dIXO(*7d2cM+z?oLyp&84%Mf@kkC=h*8$Fk4>kW(N60tH2bRE?B=CPU&i1l?FNlJ}A+T$?|-ZVmDLF"
    "@9w6DX~H~unjX^2G?(6ZtB>hx`kDTw$lPQ8f)8rQy(XV{uVg!i!WJ^XY$amd<v!DbNYs~sW{}w{_cP*PGe;f(9rc-Ce>ftMA!ewl"
    "O+|r4%y8pkTL-2&DI?5Cb31=`G^5Oe=C9@<Gf4ktPEyq;%4qYjX$4~(<EMbFvzgl?rkJd$MSeb~1LRRd4Td4dn6bt&*LZ!*e5K>e"
    "cykJG4UyS;4z`<M5}9ZoHyh#F%_xZ))VBKko@7?YH`)<Bc$*ZP$)-@Iu-{Zu00y2gKfxOHndLMy-8@O$e$c1P408|<%rrkR@3APT"
    "r_BtRWoDZ>c(?{SeXe=NJZqja&*O)u$lQ5mzF8zMm<48`Swy@So7TF-{DxmP$ctt%s;LT?DP?ve^(9jo1T8g>Q$x4Q%VrH)qp>VA"
    "ui%5_rkYmMS51joVV*Xxnb*x5CX_eLO7oWS(5b7;YV)>v$GnF2UPF}Dnss2Vimo>sK>kKImcGmJ-!q%cX0wIJYz1{=+4JvUe4BaS"
    "YzHqNn9;7Dn4M-9qt+$sYQw%=^h2}T>@j<p`w>vE2DYxi&qwAT?6c3bm;L5rbHE%lhfJyYr}@OJlTXcOrc^#R7vu}`rTNNyZQ7g5"
    "u<Bvc+I+*2k2|GlzBNb9zsSd2wEZEn_L$ix$IUVH=}yPqXvV74)$Q=n5G?r){`j|f*_?u#UN9%%f$z;p^Mm=({Kx!cem1AfY4eLY"
    "W6qji&2MJCo-^mo@34YWgD+ssVrKh?`LDTX{%2+|k3Y>NQ^0qZY0m0kL8cxNwOvg&a|wMpmD*Pyg?YU(cCzj?JM}Oz93<9y*0+HT"
    "Z38_abv3dJPz<rXhX~fECca=2JBk^Vv7uaH(`>pO1Ttz;dG_JiP_DFPt+S|{E!C@RGtgV!Zj%bOBFs_IR>G1l%y$h+wz6#mmb-xC"
    "Wm?4+NhO<MtJ=PDHAn7_#{9cfvz}D9EhI9_rH0KWVzJh=nf4l+CLK`P*V=r1*oLFkvbAj;Ti4dJzSOr3Y(v|~UT3ejjcpzksEN(8"
    "`#7p6O>J}dteHKm&Fv0pVNcM1d313%*ecAkJbI-pwJF<vr#Z~Hr7b79b{93JCKk7{H`+;bSy=`xOdoTT9fYo_#dvx4W~{8KQ&7bB"
    "Fv2aiir#8l+e1=G+t}N%wzE8p+G}gmv37)1H|>~fd;1S_yR9!BY)AI)WDlS}?yz^-^;#X~yGA<OmpE=ubC<oFxf`3$Rt2^Qv>uj#"
    "97uzs3T<8OV%t#JT5DI^%{JHWwxvCdR_kG5JKM`XPPft9_OX5KHPX-amj1SgW8Q;b{$eZ8tM-z6?J^x;e*ueo(OgAnq5FtNHO<94"
    "s_*DPBHT{~+0FQWG5ynXXwfNhza32c9<Yz;5IfWkvtv;x!|ez=#E!J1Y&T+pmrS93(EimvgoP!#%lr)=&xFlJ+qvdpEPEVX(+p03"
    "5QJ2wpDW^MV^Kbt+6|sQqL0{2^Qawzy;(BW24*y#uZoS2+4-ge>^{zpw-f9{yIUT&lWeiw%TXrVc{+tCr^!_Ngq>!mgAtE?rqDb7"
    "t|e%pS+Hz1s$;HAQhKn6+VrG-%FeKJWTt%@zj<V1C3_<*Fw2gIQBTWkJBKLFwH@^t`>frF^4Wv#Ee~Qk!{R@Kj^}JSeIEZ#)_Jxv"
    "OfcWRU>7jrWO|V0RHub@kzLFYOLU2?Aurm_@{(O@7l9XIYkJ$R@-qH(H6YQQ+K3vp%w90%sl~7Gc|If71r6h{cDXIqvZfqfdexSI"
    "qwP{oR@j&AYoKHth|8v~_COcEZW~jX-muyFrp-db=5mZp^iwOX^Fl@9{gz$D-+P$DYWuc*$G&E6H{;Q(_v;9$A}(fYY;EGU)~>UQ"
    "VeuApue;28yTKkL+jp6F`K}bE*=0J*Mmr0ihg7KN<z0N$pYPrSvExw-b#)g1kEd%aRrlItH*;K-Ew-ohl&#i%K2iS82np)4j_ZT$"
    "`*u4R9gynpKd?LO64_~+;P=yXSySj0mdh@ii)XF|YZNQ3Yj(3`HT}@;wtMVeTc97=-e6PoANH8+vqxmV{n(DAG99pMoZ9ERY${_O"
    "Ja`a1eoRKMwTHkjyo+jXFQxXMc0UUI6N{3U=j2nOS5ZE*pW74KhdpnyyHMC!aA6xPxPzGNBytJau~b@{)pQG2z_2H%c}K~t+32Ir"
    "RKo*wD7o|}tzqD)%rA|xzp%HVqsHrWl*O0!EBlRpZ7WH!E<!i_V#dfB=6zld+qNcV)CKa5Jz~GLN8#DdGMrkzmg?!7f7xU9xc!do"
    "U!zZ$HS%wpWxCKAS1>2wvQzX5FY~S&?BUeXE|Wno@jbpsqaK~K@7f>ikM=(>b`DYg$rkF*HUlj&#NI@|eafD;zu=jva)#e3XUWN5"
    "Vdvj$j+}#o4yyCse!P0#p0G#Z!Qbr#IJZ=*5(#&1XRVF3RQ_NNrC8Bf8c~g=$bap0Qx30Ov}dv7fA&w?KrY$K);Hp{W0YZZp{>Ea"
    "dd54W*7Ll};(HD06&j$B0`DmOe(1HwyOB4HV?BhXU$3!Op9)u`iPwqTJx^!eSlyYJ#2a8cNf~dOT;bIt)6%>nHr>0@J3x1rN8hs>"
    "J}ghZr*lNnvfg;TM5pGmGs~3oGR>#tWI}{T)5)J9N3ZfGp{WYtoyGL6BjuQu_bPZX`<^Cx%WOq2A3xWX6L{IDr`iGAl+!oBa$P#K"
    "7IM&bkV@VGsq9VBD&8!~@Tz(%u<dGZqimFF-WvLlKP+93{avejW9Y+%*fB6Ay#pw#3zlnmb!<(qJgi)-tB7Z&ca3+gw~6{x%UcIi"
    "EMZQyv7(N**=bOntaUxQ3~w8=sL8l=|DHqblPK24vfPei`<i&uonx&)KbJ@YuYuRlgHfcBm&Lm_pna{qj{m_ONL^?q@muA3udz2&"
    "R%sJ2Py1<s871ps36#Id@|t?Z($)l2t!7>uyT&&68mG`-8J1{6Hl3hz-9iuC87;KTw(w?B-EZ)6CELsKT6(!&6VuAO(R)`PmYX~@"
    "3^|eKO$Eu@;HjIvrgDonMKbKIUQP0@i?;UqXhUh^-R2d;J%MTKW!QG!d2R1~M8>SrruKHPH_SMUZg2zh?cjCvI(a8$fW5=J)61j2"
    "t)g0V_C~O61=wLb-t8%Od3SpsNj_sQkpi#Kt0i5$H2k@Mo~6E|!~9*n=_s%U*!?&i%QWfcjl`Fap+D&Dt?RN^ntJlR>CVUnwuiS@"
    "dg9w&Sl!#(!*Py~0hj5w`*;PQ(e*y(w6C{c`gu)cKQ*d9czjrjynDRbDfD^RRZ3q`8=ZClg+G}7udbPZ&ks`7dlA1Q`WNpw*u2-<"
    "2ip(uTF7CLF-0$!X>y;J!Tbub{Yq-gZTRg^IB1~fI##8VQXS;o?=2w5d>!mPfRz{Ekags>Q+sJT#Oo|Wy<y%(j?|ONut<h`g)sRD"
    "Z!F##>5cLlf~h;`r52)xi{wF$eo+7FJ>>n(8|_^}Ev3oB-Xq?lUKe;lHKc|%U}hK0wfJ<5_cpaKPsVcGG;B{pJ!ivwIr5k{&hz-I"
    "3BBxc>cx2WsjU;dbSl<FFNY4LuO0-wEvb)%RPqvi+*>J=ydky~@y;jH;dJUiBl5Kvgj@p8lRb;~JIf1p3eg)0|4k)_o?wP`IAS)r"
    "wE(nrGevaor7}^bd98K2S5u$#y2-=%K8;+y)q4ttYA!RpYSj3ZFy6gdU~}QAhxBFQeunH#mziFXu2<Jvo`LTNQ-z-<H)erfclM~N"
    "+>a-Jk=bO|9IpZ0^#Pgd4UlIz-ka#1@%pScL3>k8j5(t}!2yqxJI{H~W5;i{JR{EI`}y7r@LywHK=hj0g<h6vYtEv_%F`vNEYwBb"
    "Y;0IePRDXP-3hFX@0Z}|IdYY^Twe5E@|JqbK-fLvvYmS7)dkZpgQ7fnNiWNAX6CLSG%~M{Dc#Hfl$GiMGP4^>B{0ii9H&*rGRwzd"
    "v{yJ*3Cb?lVG_0*1^-Qv<)D56C{%G>>uB$1j`6Bj7Aub8(F<mRmUt_$>Rp(830n&OPiOzvyi&P@)#ucpRyM(7ljz*W%In1JdbXWp"
    "cIz8nhz@#_y;t&SFQRZCuR{3ZEw7jSsjG<dYW~VZ{cOSS@9J4HVV`^?eduQ1_IjgC-tpR+7wC(ZNTICp>VWgL?9~fzt@9?it3fEL"
    "T=aNPNtgBbeFKr&=xqhp-_RGl>-E(4z(i}RxPqy(x(WVV$GdjgUJubnY{n~RQ`f`xkpWx0_3C=;3^;15S3&;nrBf%@+jMX|Lr3a1"
    "?|o*IsoR<TGW!A5F4P}%hc{DqdVO^}>@uF8&f-4p4<nQ(k8|lUD>333dg~CMR^a^{es+0j9C-&GuSS$V^mcpSu|*rAJKyZ#)4kqD"
    "WNR^7l<0hV>wkFedfHjG-shc#q5gC##{1aos0XN>-{@R(&?_g0yi)H9lWYFzed2xUO|l<*pYd%+?Ef4t7$WZVAZoM_`+fPsYh)g@"
    "%Q>P$(pvi^>{&y;^5&b?`Za&M*Mrunq=4+Hg(BO>&tb1WzbnW$-VyIxxDl*)|MJ`!w_{-Lh#V(tI_P)aAaX2EHn8Qty%S_ZG5#n9"
    "GsEHi7BFIMEwt@Z=L0|UzV}MCEU$dVa93A~$@%-R>puC6F;99wct28~f5FOZ`41i`(Vx7Z;h<?8VK{wvnhcdua>|<~V(Mc3X>X&+"
    "1987_+$D0xYX%FQ^_K8E&7HB6qp-<y;I<=G_870@9PcO!%Bjk^aOPI;SI=E%Y_8p4^2^N4Davgs<`mgD7iAgiR_`Dz&>jv9@ef@e"
    "omn4ZRA5fXZ(a}Pch1`_(@mncctc?Li)c}IMXv%KbPEvipb0eqFN^U;4RM+}TUzURZ!p|FRve?E;Jm}q0R%QA;%%|31|FDz)uqx2"
    "UFU;~Ce-xKash@BT}D5?Kn9vZ-N&n(Hiipw#Ofd3YF%sB+W*2HJ5p!Gj?y7KFTM04HGFWYcW|>9j3xi`-h?-L;-ycef&K|M4A*@e"
    "p%-1_Ff6*{T}Jy=#AAb)4gdTZsKeTtCF+-j2hM=<`Vv#`CyMdWi+&4}M!s!Q&-eYB905(KqnO1(@Sa9Q3T-J^&ZqXzlfV!C26DAA"
    "M6ahtelNEF6z-4xC8)?;n{Mjkzhcu<+o2E=|8_G@{xoI$8F-`6#@Kp=|D2Apr(m}<f3)d{uUwa&?(ftBxze9R{)}aQ%XB#2nQ!K!"
    "%YO&olk9n~tlygNTI+pM&Q~JY)>K9vDM!7^uP+Z^Z@%j>b+l<A<$V{0gCJ}@i0cd!HIP6n_)f<aYehdFJh?uxQfkI+%|&@dD*HW|"
    "NimF7Gj#=|3g2b;RsHJb5T4y{ul8SIt5ce;$B20~Kb<_tOP$lH?pMU)Wn`Ju@SEcE{aO<X=ZHJI+*C6CIdYBP-dyX~@(;sleas4M"
    "cB(0dJ|Q2xx-0du)b^K39Y5W#>(}$^`we`B0Vgrq8fu8+miAz<3ze;pSt@_ihJFX~wF1~9r|nXd(0kgRQ5yNp=tx>n_ph~I>rAlI"
    "ohnd;I(h)!YauJ;I{$kA2$?<Iq*EV<q4h$tXa_l4Pa6A+wTa)7zVt<J0^`Q8@;LHLHOpTiP5mSAN6a`K_;d_v^oV^=Uob=Q?gIMe"
    "W`1+Og@1!z2}aHKbNrTmhRyYB;F(r_c{IUHdb%6^My7x2T;^+Lo(=%(H-V@Fs1*3Xt4nSAz_vEU^g{)7IPNOrV!2&fsXO1U<g{vY"
    "&GV1J@}=xuS8w(wl68kUVka_bIry9D-Qv5NeHnxnqMp;hSAl&@Z}kfpr<Ob0?i=%nnIc){F>3N*wsC7BPT1$PjbCUxgS(~JqvEco"
    "(VfX{egQ0;$KGxIx^&-1q@7<Z?R|&P+reHDSv?W_XY;#rsymnn5<B?W__Pl{>Dtwt*ZxG&laBrvt>$+EA6KSyy2AL0+~E&NRk?J%"
    ")9(x-a?y%;a;@%lS{yyq*^lKezbRU24c=eC7Ozl;M}h!%b?jX_(uStk-0hEq&tvw<_cP4|o1co;N${1e1^yuP?-BWdnrBU>PO!VE"
    "LyM%)-(}oYC$~;w0JYckZe9GYpwF?m%KyK_i0S5ELZ>fgcHR9ncWsq^ZiDpjd-|uP7xoolZEwGi|2-r1_3N?MblJrb*NE$Jro&#d"
    "saYdIXFfja=O3r9Dho3E`$fJ}MkDcc6%?xF_dR}&{>9H=q~%2YSvka~_xkRdL$(g^pD@>e+gwIzAq!CtEf{gI<e2;Xf&O3_<Xbb)"
    "zu(^lOPA<X%;F4LKiEGjhwL8NBhKp&_|xe0hWJ-<1b0nts6Wgf?vL<als~+Y{-2;?I+}bGm@h&NKj^#uWS_cg8F?J58;EO$rGND+"
    "Y8HLmL;m0V9WvUd`|=<0yP8J&u|Dc|plZ{z_-$k?F@KD2dosdkT`u!r4yP4fk#YVy8ShWP7Zd%u<|BC=`zOH?#r|Y}ia*tV!k^|("
    "_n-9F$WtI@2Dy}r4VmVW>@@qOqs;VOMbGs+n)P_C5<K;^Kg(ZE$DL2-dKxZ2fCh4BBPz&je~!P$bJw=#`rGt+x|d=U<}?1Y{&X{0"
    "3-via@SgYoM9Ec^dA_S44gq^*zVEJ9b)@$#K_wm_^1i&__w#S@4(b(nCtVj{#c679rm15G`X#!My&X=@>oIL>M&QXsU}UlXCK{##"
    "Sjy5R{)_B$4`U9Z9=(M9gUCZg3zWc!dAgKi2B^cA{Z6vX&%^6A$gcXDVXLIjm@RMFwsds^nfDUDUCr!UX`T)w4$Gy)Z7c0lSED=9"
    "Hy2{%^LRw`TJ%kSeZ}7hFAmqcwV5o3o$Jf1{(AcA6LdYDbP%sxJ6%eM+zPCG&37wpO7wOA4Zj`P<IY>;pvODOKtE4AnvHZc?e$IH"
    "&9p#P`fvHe^j_VntH_sQpkp<Az3so_uVL%;V093)bZalxlAY_B(K_EDG9CU{?{6UcYwJe8yS(ckgt<1;yVjJa^+kD)Q8xKi?HCv`"
    "Fo79pzCx)t*3G_0P3%cNIBlK-w%jV9^YHy?8D)3F9g}2>KVHk*Mp%9v&uoQ9I@3S=-QNZ#hcU|g{soxlq-^(d=#3}fo4w+$lWo);"
    "c=iKwdogu&l39#L2b#ICWr?1rs~OF4cVKZ@^_kH-b}_xhP9nVv{{7J3?LR`ja#s}6s9mUL(7O*PE{3T+G+w63gNe3M)8DXrL1KGU"
    "S_ze9um2Ha=JWc8Kg3Rz1G>*|Ow~W8`^m>K>aOvA?1$ny+|_ib^U)$3`F=LN+z>lN-PzEge0RWa&ij#6frI`bzlD^-C+-Sbj{MWF"
    "V~fe`Pw=yX!IpN7*78cIV4Gp}PyIH20LtAJiKTQtpZQzJqOa)!KKDz+t^IkLS518Bs`EBpE-MXvP$&E{jy=BcYtgB=Gez}@$d~>}"
    "jxvRA{wseQOnX$n_7B6xg5BBrjbA87{BObeO4x0X9QFU@AM@*?lrrSFpXW_C-}&9#3LE`5l_oG((nk*06YQUj22A7k_kN-$eW%)g"
    "@Jmnvr&1kh8*tPLjqldxWy@MAl55a58TyrVd_ILvrWJGehR)<i|3BpGPyWyTDSwPSBP&o#Gw5JrIqkoPa{UEXER{3<S^ro62N>)("
    "w4UlTX@fU@v&ZF}e;%&=-M;|$eGE6I$scIE|5EWE@-O<e^*8^2Fnk&Kpo1wefBHF8k;%T$J3NgFxCG;kfK4xx@r5G6VWUA8c~1;~"
    "<w|SQRBSL4Z2dq6*G;VvJPXfxfgjY=ASf?k5C!Gw{f<i<B*A_u6I>AxyP%t-2WRxkplnbUkF3_AQZBeEC?8}=g`i?EL9Vf7O{Ji<"
    "`B*9kRf2wS=@Md<5mXH>%hf@(pnA|mY6LZdOkQhXjU48?(`7$dv`K#^_SXbUsAAU!6{J=$7(S{Ur0Yeg6VweJ)^ELfL9x^iO0+@H"
    "Flfa1nOOCmUKd;+xU+hyje}S#Yk6%FjFqe)Lz)K7f>X?+tTqpR0VStgji7I?BQ1h*dPC6GtRqtfgM<?5zhj2W@IrPlNqo4oJZzK`"
    "v<&K*GmM%;Zn-m56QzR54VuXfL7Fy{RzaSu(Hn!s@`QI&kjMOP4sHo<4O$0nf?RtWUTzz-3)%;V<@TUMFv(VyepvIEb_|y3D(?tg"
    "X@>0xe{~9~=^X)>rpqdkO2M5$4lLU_*erJiV%q85L4HsWlxlD7Cxt<mpli@A@T7at3Euq8J`evM)gHk&+B4{dXHl$rzt_~BhADan"
    "h0-TDh^nt6eer2^Jk~GhA5<_!!Dic6?+JDh`@aN(^xoiF&^sWwk7IYB0@SgY!N8yas%=nkfjm;(fI7WD_|3N0OfxvZQ~E$KB)GvJ"
    "8q_3<YU;4yDQ|etLPi8_$<>j;D17iBvHUA&YK5|RC@3(;=>luY--6M>!$BQ+B-r9T8q}9DL0MDQEVE++ry5K3v0z*<K9~?p3?2_|"
    "2)?mXwK84oNUD)jCZB?qNqB4=xm{@6>3HIO0v4K}#lhrYN-!MXuJR_qSW|;1f@xShJ!nnuqWWa;R4^l$8B~;~g9S1xxQ3461v5LC"
    "!)&H#;>``V$uq&TL0@-`#y%H34{qjx$xGVZ&Sw_2sqasNNN39+YUC~6Nx9veB+D{6!c28nC0_^@1Vyqi*r)UGTqRi)^f8NrCBch9"
    "Klr_q>z~nsJ=9tLQm{05Ihd#0=vtQruLR43Tr&U`Red!;Ee4BqMethidhkY2!(3w;@p>~@8N3y&3RdBX6GUmgaawtG@Ur(dnA!+O"
    "zY`3QHG#@n(9ua=m36@)Ss!c&d>up2*VQzZpX|n<f%h(cA7$SQHi3Z6{M;v7f>%J;)}RBK_;;|pEqFh88NY56clEv)B#fn_D~Gz+"
    "9<;!Z{oNHx?aJp<w26EW%#sotd+W5N9cBCLj$kL~sfM=SfY){f9|pUF=g6bVu;>;%6;fT_WxqYaCE~d^aNm3sxc+m${DVDb!U%&v"
    "-M(Od(1_eCmcQfO%-}J+_i-@7I}rQ?L(SHM!J%L~-M|7V4gMKq%O^pGEz(beop@)7d`9#(>93{;#rk>hMKHitM)Q6d^w2fbj=l0#"
    "@TT{5a5(rTDAr%-#mC}@O?o8g3eyfiy??E{Wfre*;GY_DrBf9shi`)d)WBSNsvmTne>B*K&N-%;%;{gjAUPHsKqs%(Wfm;MOlfkQ"
    "nP;Xxol4cpwMXPuD#v$3sXv{{LH&1dB5>=mBWm+`ZzOdvVE^xflf+^(47G-?Bv-x<=9?dak71#)RGYE#WAL9~3R?B2AhMZyN&BSM"
    "8uSB)_whT+w9>k!uGxg<*+ka-91PL<rW<U3DsUC0JR_VAexWkVku$;BAXi+4JSD%9KM(0|!G3R#G~u<wckADW%0rqZ=YsRWVSB-A"
    "<*k$7sRb8cq2c;RP*&H;o7C%EDL{{nr0>`-{|)wIsWA<SU7EN)O?3qw#R~SQsH3nT&$zQD^-+l%Y;*EnwGtX)t9KDk{SQWXQ9}6>"
    "K083qSV6WC?F#fft97;h;N45r9D%AGU}j2P(*XV*Lj5h!$$BYRjs~3XHPSJuvx_R10|{%=DHo`QrBt2cvRzGhNo=@Yy|BC<lzZ9F"
    "506PBs%a25(*4?wo+u2{sOVAHUE**#9FRdQD#>Z@knE&hY@>4?Yb($n3}eoLNy4#sQgsem-mQtLnYzMJCd`DpMo?kgn#DD!V|Ui^"
    "5K8Qda0vQ5ExZRFY35cCfR|=4Zxb194uQDq)UDm!&zAi)Jsb%Z2dDb=n;4@pJiZ)XWa@Tp#nG<}RkA#HlmqxDFqPqivSABxy?S?4"
    "Qn~P|FvfrP!Wu=4eE|fW*Ye>2dT_T&!Cn8a5MFJmg!rbIPbT1tDnv16%!*-%N2?om&eW;Dm%YaFzR6FmKpmz_#pP@^-z>(SR$40i"
    "nTtxL(5+7&i?(prqc*cmZ|vDZKDE}$VYV!@+jKf()+GK3bDcm(*;RT_pUZ^X*dr^|A)jJDpZT<rDq$gfH3~JlSdV#?&|w*2)$o8^"
    "9d<_1k3pkW3#*4U!c0>$%nT38HQ}}4Abr8F70!aWvrLw$9bS++;dE@T8<runi-_`csTXFMWm-Sn$((;DPa1^1wPE;~_nC(e!fDb}"
    "t_z*MxE`AuhfTs-WL$I23Xe)(X4Evi2+LgX`V+-8Z5HlE>opJE+4@U#^M7iK@P_ba$qr*Ww!L^PCrsCtVQxqVC9T4(UIV!?Y(^(u"
    "i|>!i<62;E3dd_+cypMC7R`_*rnTM@4kdE8hONVHW{<Q98--<2;B`$;81%Mq4z;hobSM9oo3`O;uU$AMwFbW?-F_QsAO0Ndk*kS&"
    "W4S$aSMc_0hwvf)Suokn4ADZVWY?rte`KR~7*!gQpPAY*>=d?_J3^vNpPH%NP@#8*>NPT*Ll^G~DHeOvzY9-SlDosQ=7fCA-0Pw5"
    "k4j4~S9S;aVFB|zqEC6<r6Jbd14awUz%Jos=^AzmyN9RcL;t#<N7yrLPN&ri-#!P=Woz%SPk2!Kz&L$FWBP^t!>Upg-V^>M>?k9d"
    "%e`z_0n6O=sBDlkAgp9tqTyBD3b#au=zZZPRAr$I4C}yA<#kX<K_wr{v;F<y;864dVml<v45nd!FV}-$_X3k8L&MRjs|Lfu+u-_d"
    "J$K&ply-(ShKJ*W5n%-x8O{Ku?i$;uaDY4*`uf*!oA#DiW4$YQC~P8iv1F^>Xs(fK&^v#_+CCuYpdB4<r`0YZvW8ySU9~K)>riPO"
    "h{eO<DsABHrmN^nyz=ysu#G=b9tDlL@}yauT7Q~l;8Qa864mQP8535QisH`IozWw9C#tN0w?@W>kKv6^?YPjLCkmOH>n!rrH{-($"
    "80KkWxfRyUM2SuaCx(xMm!4GQw@tQ83cFCTi?le*kwNgl6J8U1IF7isNUc<#90u|n%1G6sWwLb&(a*-7O7gtyp@&K5@2|D5P7TM&"
    "6JaZz79O$F;nQ~dBsS4&VWT^DxDO`GkZtsB)8(l!otn@|W`LFP>aM%KOFuO;d^*ezW`%?B=In4zXmxJ*O!#cr9#$Wt&xQT98$7tn"
    "BydeWk$oPEbL0-0hfn5*Ze7f1-oF4RH*x3jIqnQ<m^+Wrje0a7wf=kw8hZc=x(Cs^2q)&kG;Vb@6@%k10Oz@~5Egw1kG0c9aP0ej"
    "zAUDeR5we)d#P$CB;T%-`}GK%_99$VOb(ZY(RynMEZhK9Tvc8Qiy3cem<_*l$A;&EHfVsVc4F#Uw2R%#;obgv*txvkugk*v@(M>T"
    "3YSxT+IsGa?W>`?8?7X)2y&kChM^oE@ZD<Z3#Njs2#45B`Wo9Vv+gQVDMvUW#bm3>>){*W(`b?`GeP&sn|P=kxl>+OhHt?!y_j)h"
    "X4V=s4g*cC(6mcnpjF;@B0oW0e(eBh6T#{P6zV|JPpirhEtk3~;MO&+3VC@yX;V80ek!%KiSVpob@+DJ-KOa~VJ+_r_2{TJF-`D5"
    "2QsLb<E;tZHHw`&Im{wE)`siCDb$$Lu;?!1)^e|h<u-&H!!$qByc@QWRn+hdJ3!vU|4q#8#;LMR;pXs!-4bpM|L)k^J}cY8=GtG~"
    "%Hzf8>zT}KHafAog!+iKGL5l$sJtJx)a~I1p<7eB14iB%?g~E)cf-P&<b7W-aZ&aVrz+I7ny8^Z?))o^evj9Inp}mtSqORpQ(h-o"
    "0Vny)x>!F7`%^3PnBPCb#`x+bw86e`h3pSM4$r}|Z<zyOCyu>^=o}0Wh3<-QX;=bhKdlAw&+uomJ4-$ZD|w%WTlKRr@E-B^G0rml"
    "Hq@PSBvS4=YZo#wVeHw&r<{HcTYSOsDyuuMQ-T5?ZPvr!{XzX`<5r~2k}t#A^r$5;3`$?V3ctpVq3(PDc)G=QlO4e~%(gCBpwbc!"
    "IEk*vmLs8C5%X>MuDWb~$4(C2eFRJ7D3-bitfAiii~Os}x1k<`0q<3J7G<va9Ul*Z18RVr<KYst`D}gFRTjF2@4|mG=h1MEGOu$w"
    "UQfUeKceQR5aFTdlq|X3cRD0Xz7Ie5YHMRX8RptFw3gKlsHOqT><9R!NPonF8vH-ludI{gKjBXxdlFsP&tVlg6`qoLXvs8`M7Ep`"
    "d!p&@Bbu9Z6GzyiZtY!HzC8#^mdF8<VfVOI9^sjAG+2E_&cZ@ho9n#$<X7_fH}Wb#IqdMxQ3=n7zw_;d@Q?7n;l=QO;STT5u)2A~"
    "e22gG$R)O2B2MiMlFMYJM5CShj56#2`Oq};GSx&jnxbAb6hFEvoo*GS(nlPX!>9+3--o4*&2e`mMlJ1L38H!uMx*e_Om|jFI-4k}"
    "ow_^j9*LtyD1$hf?Hxxm4nc+a=;YlX)Sb6WqSIQD9M}<zfNNCBL=T!PqK&%3Z|?5h1i>T7?6UCUpp;(iEE}B9qRPHXbC}VsM4GAR"
    ")UC=Xl+o(6e|mIfq*6BOAdS5LQKyPiS2Om3dv`BVxu}G#l=&YG+G}+(|BP;iwXTZN&?WAgiCeXLgj&)ab=eoSb_y;SuJ361=rVQ>"
    "fpOeAn+bedQ7S}z(Ua?VKUFG5N9d6f_Nx?CjtXItDp58WkVr-}L8?ZJ*>kzLHJrosH#?k4me9paH&;g^%xZjbv+to;`%q;&a)jzA"
    "#cI*#`Z-m#)ZM3qGDwf|rMEp!{jNhV)}P-Qc%dwR9VdTBNJGD&|C2@e%Q|i7Kj2r7YD6ofW|SFS6IGOJqnTj7vR|SbsJ3ZZE2?g4"
    "M|GmQky|Cc(A0}OsUJ0nz9Oy-qdewX72TMQj~nr>6y<kaw3Lc<eH3crs7d6yr>tm=E}}bb8r7EqdXi>QbFi>hKGqh|4N-QK6TNN@"
    "5btVwowpJTonmYm<wncsqiRU2s12I>M!a)Vlo$22>2h<lPjA7Gw?;~*_LH`b+M5%or#x(LDDLir=gFFeRQWb=SsT238(aJ{Y)foT"
    "NINWRAKfOmM>W7&hiE@h?-<o&9^152R6V#Osu%r8#i<8>K1!C~8TE#NJ4X-rcSZZ?gkF@}<nE{{W9LT)OhMEkYOL$MPUK)~Qy6vO"
    "o32rgbc-TzJX^a*vu!Rm_K4oa|Ml^Dd+izZkzP@v&82r#Oy4~dA9a>K(dS;})D@K(Fkj!Og;ddg(eCgRIZ_`)U7~*XkBXRcXY%Ww"
    "=vyyK{u1?|-p}-|0QuLO*{N%N7u{XUrUlr&BU&W)MgyX4dS5gUn}*0CVwE2ais-uaescMO4336-4@5(vq0uQ=TABAqnMyRrrmh_~"
    "kz;zBe8BOI87GZ&SX7ygXAWquh<ERi;ox9Iw2+E85`0X8)idlO85PZv2cu2;*C@+`@=)Z{N$1JmqI-2TIhRIFTc*A33HyZErx|3{"
    "!%-)9udpeVN20a1Jz6}JN25#~6OD~Zbq@Odv1lS3GcFn*O^7B&gNSfLzbcH}&~IwbrB+Q$!JfyX5i%)SBZ0S%N)Ss+TO7G7Jd>j-"
    "Q5|<SN2W$kMAM=WBxitxm1N{ede27WUlSN$dNk1QLVe1|cb+^MJr&J}8cS!L8D*NuWaZP*tjOJ8o9Jx3+0@R7=0^A6&sJ2M4w@D`"
    "6RoGmOe1&c_4OAz@n@swqBi7jEiX-;k4j};G#@mN$KDqrS92Cb9q5r<L?@xL#_Mh~ke;(Ye;uR>on*_FHo>BEsr%j*Mmedq5aa1e"
    "OXVpq!@4!BT^M^2{yBsv7DpqgAxomiqg&BhuZ6wk#poDa;0bvNg!i!P(N9aG?o^wa@_X=dR6zfE2D~kc`k)>6;^SAMGrBx-XI{=Q"
    "r(fB3qt-C#@+u5{033X1O5m$DWS6_%-dR>e6{x<iMXyIgsBTB(4c?c6{L}dM3VkzL8I48N&)2u2ox0sAV*Qw$z9_4r>agbms%@_A"
    "m0Bme7^Pm;td1I{?jJ6+E#&QJ5|++2bL5?98~YaVvnFZ{C$4pfA)^xS7m&F=`ps@&=4d=J|8d<I9Yp=l&^&oJx`ZN_$>;;3&GKHf"
    "350BpI>WJzsK{HQtx-Al>P<iYlg{#o%HJcmhUEn_NVY}qN5gb`^Z|H6IYzEO+8Mb!J(}7bI*OUPYsc5(fhK0By1Ttkre<(2nqU+C"
    ")UIfzI*&BRS4Yqz9imnGgMJwKsq6F4fuUg_p+>43IW5=9Qs1pZSV+|CP`7U+o9ct3M^Kh?P?CH6LQrxgDlVJqKgy1kDtNAj8Ld00"
    "(D{tG4W`>2?TMC?cfZKqsK0y^tp_!W^&jNt?PebsE|i$p{^$T%`f+psL>!C`MLXz?j-y(t;Oj-$TL?oHk#p^IEw!F{3kFJ~e@5rM"
    "N5fC3i*8L=4%+zB=&#{tkvl8-dF0M`3=B8Qv;Jz`7dF;&u*b7RBQ0zuUqoL<ugF)?*HLBq=EG5zd=njky{G6nW?v}Z!WNCm-j=qd"
    "?Iam`H0oyl6)n?UFzugMR8>Ah(T3CoV-~@Ill6pKMW#-%IzPH=EoqFfFq(@tJQf{?Q=Pu}F8X(LP)<aL!Q%I*g(+lsW%<NE8I{)`"
    "qQ$W9kFe1w>bUD9s_8sf>_70^f9)K3-L$knp;dlH-IOD{hxjeYHLEijrO-b`MG5tERD_?l5FZasPzJkxiPHR)at3^LmIHcJ&XVK5"
    "M!!YpnBjT&d?uA<30|J5ZTwa`PZrwW`Se1xUEMvQ?&%8dUK-UuqW?zIL02)Tyco5_PydSyecqpu^N_o@eLEgVQtJ_mQg_Oagt3Z1"
    "<t65Rnd*{7eX)8#S5T!a5uL(zg?@eh9~u_Xak{5$WUIvEWT|MJjSp9#ImfGs8;Xr*^S(;zSq@96bzbZg=VZqB;~?&ty2CQW`(f;^"
    "H@P)ZleMX2r8H?*GP$Qj@dCE$?^ZZdx#Rc+<7*O^fT>KX+afAuC0h=KRwgcnbDEH;?*8`U__3Z`5kKmu#h1|g$_&?<@^W5(()9Ss"
    "xNJOu%$RS=#bf-}7;z7t@_Dr&D+<gQ31l!<98BFA(v+UDnB!a(ucuELVm*_g<>PntU9E(d7lXYlx~5|Gt$<JV(lH*wQ?r6i^oLi$"
    "K7n_U8kd2Jst`9vXLXi}@gaK43gGlc^MaY7=b1;PIFQP5mDrs-pRXCQ4`xgBTQA4m1#Vm|7uiO&tQwyJtGQtN>Ufq^i<`(q{M6gh"
    "r<v;U0l0K8jD(&b8|rv9;+k=0oXH;7#Gy3su8r3)moj8sO;lXS?+jZ4W@nnbR3z8hMp`S*mmQKve$<Y0rA~a_tCG6!e5(%BX5LnO"
    "RX485c<zqmG<w)0DAs!MQFyw3+|YciU5#%}(Q}_jtrLAn18D#fmct;I@Xc7Ta)dZ%$-?j*+mK^j6?XB)IZLSDX;g~7_@z-ihvT{R"
    "+Zpz{c)wmBuYmbS;qO!I*?^dTr)Tl<dwxy)xZSO?)NA3bSBOUAc#<>$4f(0nGb5;1S+V>7W9<Xdw$kVC26Ij0W^o>#a(9;0g$<f{"
    "j#;0T<{-EQb1Sqr#M%6x17h20%eYPI4D)kD*_hmTv{sEXbTO>vqi@|EUHPds1Wx5U1hk4P%Z>37#@;Orb&dY6uc1h8im!;*2lI_%"
    "n8ieOjOO9Vo8wK?&B5?%hL*Vd>g1OA*4V8%+@!7JHt|Ms5k@ra)SV5uEp}LJk$MKkellPTeeNc08@G#3h*MK^E~Y(yZ_<`zbD)jP"
    "?QyXws~zI!n0LpxQ#{|ebDC~F?H%}~m@cw1b$K~`yUWy9?VWLZRK~7U9dMoDCbUOoKTSFlha5W?W!g#HJ$Nn9^sZyimCEGEbTGOr"
    "YM_(MUGd%VJT%9Z-gHx!yss<yab5G1zCz@4=$z&e<&jztPd9}`YM$1Bt<KR|bdpE?NBs+?OWZYnfo`W;JdGZqK)dtzQFVyz9_OWc"
    "ynWIm9z^#)L3+kZsQ>PchhEHuj>0TSt&((4Q^}UY=6>&}_Ktg_WAEk2C~3LDZz%U;U5<R~xpN44Xx;|YdH2+ts?kQ`(!s50WAAf%"
    "3VZutW8b(e-}d9TJ62P1SgbFV(0TpiCP4$w*T<Q~dr}lvVIH03p16TGLjDrp8{g_}(|XvSr>-&#i0_MAn?Sw?xd){cpY4YSYKU8B"
    "?C$EHBz573pJiY?DE?FK$KQkF-5~mbc!GYTH=1S4A#hJ?qBBmDRi4vGL*k)v7g*b^`yCb!$3sp(^mV)nuaA@*G+?HVh&_(g5^ZR8"
    "WbDptthLnsxE&g9xjY!VUi+`{7P`;b-br%Io%w46?gudMhG^UI<ZhNc6t|GS!N>2|(Q#YzaNLcq;u>{pF3)Hhd9})WB)%Zs;Qq(("
    "$asA;b}QT`b2O!f&yz9nVjYQhcZD%r@9tWitUKf*d!M*2c$m7{y}*o(cSW!0tRRy)Z*)&!Vt(g9`Z$g}J}##d@X60){C1g$#i#V~"
    "cvAcgwY!`a$IQk~#<nSJ>w(SnIyHVGo)#xyuCY#!E6Rg*hCJXmC4P%gPt{HT)EN=CYUs)Madqn;b7i+_fO2{&E-*)|TRAcV4rnGb"
    "V|O>n1>;t0F96jCUA>d1<MwEQT$vTSo@I7?g5JHMnQM+xJ&wSMr7|a;i>Fq@J%(<-yp|{TZWE`)92aJbPs|Uc?r>{P-8vx8#Er?i"
    "YWjuUEobSo3cyGp&&C5}AJwF;Sx3jSjtV+1xTLkUs^03k6>FVj4J?vJ%~>EriT!ghOGW0NMYg*q1{qTaw7YZC?uj%-yc#m6Vr>u%"
    "*XQHa_$LR>wz^v9#n;Cjbg0aaUx+)Uo|07?o^w~jK4p&tj#$9h8^Cm9tOVC~AZn)?y`AIib7a#(;@%xh+^g&9B`@Kpr@Ymg?W!w%"
    "MloK`)^f5ao<cSSRETeE9cgRYP!-($g-@cFjHv)O7cuioWPW*kRRp4%^7%G*9?T4o#qp9jo!IOLcbic$FUHHkbUC!_9HO#=|2=V9"
    "=B3zq!QCHSf?n+`?)u--*scHlU7PD0`1q8pORfHX8NUw$@w3=#1)~__R=<oy&mVywPf>H6M!6OR@Bs*DX-A3kQW{$>i(iQg<&utu"
    "LGxvaS+8}ym2ze3SrFM&ji<b9*{;juL5x01++C^e%-?o+yGUP+3#0_b?Wo&zMf@Ed*L3q*{CfOGoMY;m<u+S>5s^3Jm2l{Xuwio<"
    "U`L|`MBa)Wi@25AM<p}pLLTo;Jw<1WmY9Qdz6Iuxtcrzii`1=NE3|85G~cd{KPAuJuz9KHe+{s%e|wP_mAW$+XoBT1YkzR-6!nv4"
    "2)#`yEZ)Z?`iK8^{0_DJXSU4syRpZb*kQk>t|bfB#of$ASs%}r`k~8bV|Mei9QNBl^>$YfI;eY!$3-~hI==(#Jrzy5iVkCAT$9}B"
    "O=isU-$j|d2mY>PgfX%y-fTVDY&TO6w=n)zkTn6MyQ}9X@l;vZW}P0iWu%X{N;|nH7oj-oOB&-%H}BZSu+1th%S@;9ep{T6|J>8B"
    "DtPb5+v7g^L3{*@=9^aG`?eNY=<Z}bAUoo0l*Te!1Fml%v$0@jyd$-eHycizrw!r4)~Lz;vMc^D?n8uk$5-nfSab(<r9RAFJ(vOy"
    "tk;of#J#aw9XXPDe-tlfj0W-#^y|L(IPp^5AJ-vMx};RMyQ6y{<7Vnz<`3T?C*4eykK?{%{5N_4PE$D;$MjV0-nqy1P`sC;mB#<%"
    "f9G-fC3=NV;ufhVxz)kS*<N#^R8RaU4X$no_AYzNY$<uR%UnWR)zv4Ad+uJL{S6l03q!QWx1YxKsmpcEXR$G#!>v2wFXAy`%@7+?"
    "LrNL72V1q%FR|sT_%Uq>18iW7M^GEps4+#U_0nI*JGDdVZ2bZ}GQoC6i5&*T3pmDeeq~KdshHEmX10!{pKLDQfTqS&C`;z;B?9ig"
    "yuq@?<%%4^regS{i1A%FF~qtW<?dFW#A`t6i7Ma5N8{bWzv5%@@wk$$WV_3E@vUJ4`FHG|N<{w_H)7<ml4+Wl&9K_{XyPMMJ1R?W"
    "l24wWj3;CHWSxokCaXJN{R5wj<r}A5e<UMMu(ykQYjSIiR-~sKXhy2LX14~_|DSlD{1l(lpQ*Nv%kt<SI@%A}tB5{Rv9p<+icfpP"
    "-KqjT9bfPQvqEyhj;ZHIRTSfQRCliSm)NoN0XY+&g&AV~6<y!YTgPAfK;Q)VE$+{^3(YwY=dKK%heLjk_sE6#53=*Wu=xeK7*~-0"
    "#pz^Nffm?5sa=<1Are2Jms@&+<#Jq#SI5Au+h~qT<x}I%-u#b_+Epk`Dlo1|_NVS!eFeQ{6BByLPW6+;D8nFGBipI<VX{}YX&1fT"
    "l-I4^afy;TX#PefP6mVOBq@`Gsr!IC$rVW#s?}mF$cLw`x}Lj(rX|fJonvjKj@Kav28(;j-IZ+H&@Y>uQ+IBBf;7_o)SYt4RY_mG"
    "oW}ddsfd?S=S*f$WwNo{-F32_5z8m#!zaxjfxG{9r4-n*bRnS*uoaSZS}{3@G6|$o(#TX!7Sr*}q$a3TNqzviZ<#9c2<m;QpJR&r"
    "0kBvz$w;au`6$9!<kIgT|1C4$?2=!NfQ_g9#d390EvcT24=aO_5+dic>3*$|oPl$Gvo#a9q9ZfeqUq>{bZ~x6;xtKmYF)<`-Kp1N"
    "MXh8got;qgyG!k4j?_tJ1$Ei3g49dgeYjOPZV|k42<)Yshp2XL4YL?DOfo|nB=w2ViztAGNu%UCtX)Aw*5RSPWR!cpmwPf<ZM{CZ"
    "-KgFe2|3j`sg1YG%RSO0871Y=`WvY-?ru|<4d1kurb(JKOD@Z08DaXVTiw?@nSc*kBn9RpD$bqs1UDoP_;XEmGMCP#y>U-7+X;iY"
    "`%<=17wegeY@d^~<XCOZX>gsJY?fBZjmb?(P035{Og;Cmhn*D!__qXY(1A$YoZOP!nvA2uFCxyF#Hw}DCRya~!p7T@wn@8Wp&4kL"
    "zFlkGT_N45O6`+uy*=rP8n0(E`L07!sBX>ogH*A`WTtyU%xZswED29YM{F1+osz0HPu+PHcWvqUln%Nh$s?DR*}5J&ESMp8GW*U+"
    "kro(q985JUxGQnJ>^dD2wB<PC!!>YF8i@1oUPGcf&|Kj?p1S+yZsvRx=F3mENnu=&l$XNf8ls<01?-Z%8#Rr8(yqw}>6YAsN-S&2"
    "fs$*bd*Ysh_G*x6zQkKXo#~NuX0MhUp^@pC?0|9mYl(dx&Yz;oP$X~I-_>=VRj{{L(mUys^i67bZp}(Itd$S8J7C-RFij5Heo6mi"
    "CZjb#9ioBA26yMZyYl4j?7b)X3%TJ|qt*4cXlvB#BynqQ_6GMR0}^+&QeojE!3z4&)}}~ZtlcwF;9k>S-5SN3avyn|EzihF5mQz6"
    "nQ~yTn3*k*fytmm_5S1lY&b3Te9juFyQ`WfxpHSTnD6c~XY^QVE%^grew2JdcU9<@#hwC?z17PxS#W&7UPF>5a7`04luRi_W35Hi"
    "pq-?tb<f&sj|MwPZdC%y9aCr5zX*<i^AftO{M3Dm+vRWSo(Y+UA{v&sdsWWRQ?7xlo4|a-$)+Y~%&N@29NVo|*BRtX89o`2pq9j4"
    "bF8c*laBbn^~{6NZL?8$ZtcdluoxYDf-2seF{kl=FBz5eml5FtsU%&EyKk?f9itBt`-7=-^&_3CV3vPP>QZmZr|$f&A#>yM`2QeL"
    "e<<lnMLjOZQcqMVM5Cu>kc@_fA2c6Fzoq7+`nflae)UtlRHBvjVOXGv$uha}NCJ<d-uuI?gUE_UlZIwYQU}Z@Fx4?^JgY}+W>6+I"
    "{#x5hGtJoKv1D8_K5-q>X6w$(Pax~-!y|9X)8MD0ZHGo0jR!92#N=_do0J@oVtm;V%~M7u6QO;mcXwB3eYxFCkSWR3<Ow`m(==AM"
    "CifDRv!#2M5mmLLaaZ7{C9`0)KK}INn3QGD%4mubdby|7q4UY)TK0J=IU8-$vN|JaX=f%+C)qM9nVrl@YEeD%WiDBt1|mj+xMz}Q"
    "lTtFIBiz-R3_i<em0-Be(Q`=$*SW|rueDwm%;Vdw-t)=4B!g<-iP~7%UkPivr>8Wb!Zz0S8kjE9M81kvvVZ$<ev-q{UP#=2uZVl*"
    ")dpFR%s1{_Q()%l!eocHh$`6$1u@@LvX%V~Y`-|EWOriC5}3XMeq2HhE=sK~96}8$q)NS*42S;@%1cQlaaTEG6g{Y<A6*Kwy_{@t"
    "8ja6Sp&r}QF=fNr$GqS5PhFObq;`yiYhOv0CvFYVUi8UAkkBmk9LcdLqr32NHMGboua3N$jMtLnu+7vJiM#sjR_<rOCqwkL#66j}"
    "ANxC%(b25dv+{aU6?@-EdehyF0cq~;x;K-Lq<L~eS4cOGv?BFH=DGB1*}4@@SdG7X(C3_DoX)B2KY|C^_`mCZe`Rt}-b#8?nYS_9"
    "8?kDP9Ja@_9-ep4dngmG)4_6#yt~<yYL0cCUJf}uJ`815;<CRJbE%MeesHEXq}y0cEoovZYJVxqm`8Plyq&m}2HE;fV)dDDP2zO%"
    "APIxDiMxAcU9wNsqfIs>8<RuifP30xW5#?JCUQEiFtsvzjov}z*I-!#wwQ@8E=vzOhfIBsTC<)RuJQ`tkM^=D8Q`^%Gj?;bC2?14"
    "^6=%>#H~phM&Ek|AN@TkC-<j1hHXhlQw8J~*d=&4Fiv&9pPX>DpFXCEX{E(xu$<6bn_4U3Z%;l*T>rS->;N}AQCeBD3v6v-c87^j"
    "SO187m{f63=r+5PJye;6^bu+Df~jGy3Ce_fDI#s?;eODMlJ@eC#NBb(SobCG(fxKcMN*lXSR@blZUsXo^9*%=68Q5?^VIo_Y;~(;"
    "mx7<)(ZnAo%iy_8__P9jt0y_BAGe|=Nj<k_5_Rz%J&?F{_fzCx;_jfVAe$H=joD4sP071DNDn2Y$<@}aciy4@WSdWtPx-yXt)x!f"
    "37V~!Q@Yuz%a$qZzl6Q($ss$1ZuTKP9Av}8J?H_%G;z<i($A6=<orGSyx^apx-9^s`%&dFqxRF~bkKS7dGbZ_l;@u2vcsL5W3O`B"
    "hOEd=tq7WH8kyPNm)Nlv?`)-0&*y*l9PY1@uM;tclg84(%M6y0sY5{Z38_xxbNRhdN2Z>hnxM@*`6kH>VzAUsAB~PA-ORU1LSzff"
    "Q|>t^@MSxWnT-#Rx~G@0|I?ZW-kPhcHWkUFQMQ4%O^zntCS$acbx+`IWZc@0r{T8hRO*UED8m*q&H_Gr$L5k9$H>QA`>MA||3#kG"
    "l4D6a`Exv}A+7^HB)jFi<lo7O<a<>1G`W=G-F|rJVR_U)NhAv8hvdhky#6OyL~fCd<j*wtZw?;#DJjBVwdCjI6qVN9lkKtR3w9Bo"
    "oKD;oh&!TE`6_G_o=QD)>lf<Wad_dfoJp37<GFfrHu)81t!qwE$qHq(*@nlak@0s#pL<zk>~G2MDAa9u=BS)YeACpPrw;x}r~G?z"
    "A^9WuZ{j?CF}Xq~=>Jk$s93t_pNY}wW-&-ur3KWx`>-urFC~6-nYomOBPzm`N9<yeGFrxzv1OWrJ+DkLoa^kKD1Mm()H?TE8TXv9"
    "piBn&Ss%WiCSjQ?gQ*fQN_C0KT$F~!UA;cb+?z>UW`TU8N4=y>Q`;=HKJ!y4Q>L%(GHvwP=>Hn~^6;vP<n5|H=iHln`*fc$VHXHO"
    "2mzGE#Dt)zAcTN2lCXq?B?uTW>?&%I#e_J3pdf=H5M~fr92eBEhyoKCK)?YBIF6%YWE2@3H3)*@IKubV@%Q_l=lk!2Cy?BnrMtT7"
    "t+#rqQtBtfb#>(H+HkLDe`R!Ewt9JV5af0RW4H`a@FFEMZ8LxiiO`8+_DIgS=0P)RF|Mi56%BNs;8jzgr$y%QkM0HZ6PTfzIUeE@"
    "3nrS4uS9(Y{6S9C_T_82fgT9&ei|P9O>Y3nI$Q({N4#_?c(tb_YL;2CTIVR_vMAvj{*BJ$B=oObO~thhwd^sM^WIabk?x`z>)zBv"
    "@8b*c&fxxi@tes!5`F84$Ul>s>Xp#R8DKrl^jfOITNAmt&Vs#0fsHeuN7v}gSPPxVAK;xWbt|2$QxUVRf{gou8P(yc>C{>`c7@ec"
    "avWB3t=>#+^d_g=$>gc7%sZv?CLXFzMg~zTG`Eb}>J<GsJbxx{;bu-d-4s@os_Uq|X0V0nz+fFs(`mGX<y1=teUMH@Tp(jd4f}@P"
    "oQ%lH$zvf#NFJOx%W7jMeVzVZ&BS{O_<G%0zlB~^QuAMT$vMaA)@YXq#nLePH7sYhGa#WgG?pbV<tZM8Px@l)%OHa*h_fYje%Q+g"
    "K8y}+yplQ~c9VVLz%WWxl3iKy2g|ASI%h7pR4RJAP@M$V>7uuzXO|K8%>wp#sx_kObjW!+n5|?|P75>b7h_Ca=#j5InTf>cTIl2l"
    "uqBxr{Tcc@g>Qgv)jEa3Fril#(kOwh=<uY4<e9!78nX(1rq*c&?wlxRhItN)jTfQ)9bxrd)NINOS9O<gma2kGin*!osxLz0R;o&V"
    "(b)nichk+B8}!M@*?0wHaW<Z=&&KaTM34i0J_=tfE83$GG39W%Q|d@WCUcETxzs_-#*$4&Y$!^y>qvH--43t#d^|%B!~d`1{%&-d"
    "Z`6as-zDRTGgYP*)Mt)?jbv##Ii3Wbu2gq@JKFm^MyC!s_M&ryW$tz`!=vHZNny5u;XtQs=wTVW^1-OAIhElJUDOwNTMr$$H^FY7"
    "18b@VCd+!o&3Z0xceXn{(aT$4`Oo3XTlH<)U~D>&>>!ayyAocZ5*pJ>_tq&+Dm3eMZNaFH@Hp`NHSj5iA<t~sSP?!=#Mt-2dp?4`"
    ")RU~e<%O$;wVWI7)#|H9N@iUi9@~d8&cRQI!_0Eq`7k&{UzW2lO}U@W)lpi3k&$!0{q+h&x$mf4e6pD&tJ8My@Lu7$<<Hz<@OJ~W"
    "<a0a2G6Q;tPEc2zJM}>QTfLO$0ew96JV`wA1fq`*5Vzf>hlcsKCm}k2nyztbXeQ@7DH!p7G)U(|7r_J|y-upFo2T>jVp^^S>*3sj"
    "hv>s3xm?%anJhC}PCE2SGBQrY^+WYAEqhzOMKo8S+tF}csAWfpaNv3_($nx(*_AKzlE<J!O%b&p1y*O_y9lr)0`#kd21UZW(@p6E"
    "r<8}I2N5+w7sb-)TOjU8Jr8&64|8xFg|2tz_4pbTKMFk<1)LZSd}u`Noas)n9)oe647n}<_bGyP&f!bYxx4jfc+Qt;1GHj>8mqHu"
    "oG#;Slo*>6&ExU972TstbUUXGasC8-1#)%~6;0Il0zrqk?VM?}lV!d&hOu1{&A@XPs!}~pcLPJJN3_tBC+VF$S@(b>j?$onkK<GH"
    "R6Py)^*L=57NBS7`}Eu}60T)o(8r*+a&qH55NjIUual`CeTR|v_yIjrHzP0M7kZE112=h4N8AbgkS?Tws@Rj<CHtW359@tsOPMay"
    "l5^=5rx9<Yz;&sQiXu{+r61Adz}J+7be^r}pnnl}uAZlxxbwpGn-lb?F4q-$zOK}d>8s(|@9%U6J(w2gRc;^X%#m<6aV0I(pT;{-"
    "8h7*->F&^+3H-QTte5C?^!h`zd;~wCo6wVbsXjr=AlGb+Y!6;3b8N8U1FA1CrkC-~r}T2@(f6?1nOsehU9*pBlJI+-3~th%9(Pl~"
    "Ggs(de502^vtf-xfoF9XFR7q%6lnMzxMUm7kKG3U^Bu6U1{zT7l*n!_Ehj>gAcZa}5y%$i#?UKuKYCWL(pz}7mVHlyXbtYH(#7F^"
    ">=EFSEf8zBR!3<q?%zj$(5?B8dYzVR+?D(sq<bWqN9(m@N_bvVB%K;Tu5Uw2H|TS;QOl0z!MsUV(naTOC1(Tn!ABjW&HDCe;I5+X"
    "=;1y$H->Tb_EHXFr+SRfaC$*M$m^Xy>6ht6JwSEFzlHD&+0IK^W+)QrWu5I@7kNd?$^1xs3pmbB`0BQjr9jJCtfAMSldo&>WQMAB"
    "7JS+v+N!tdvm_^kN}VPN4QabBb>s|Z4)4&p+)}-wB8X&<Q-6L#%W03zl;!LMuB57+`lOS`Z^Glo;mtDn8Q66KFM&TP$2&`?CGL##"
    "TRJf|2>O{#jh&9b<c{F~T@k0rTz@(3=3QvVWd4+Q>paz5FI4@x&M|n;BY56)C*N5|BWREQv;L8{0fpmX-GWT6(Ys-15+Te6V|iP*"
    "472#}g)RI==Y-jl<n$ZUKHWNDzrH(uK<{y9AqH!$Zh-XP(Ng1KG$MlSXvaZ)NMGW^+NF0P(ZA~H@F#h&;cPmhGo)4y-gFd}y%xyu"
    "p8krD=~{gpGXGEXgnl2R{Dk_OK7>|D_Q5=!lrSEil%bm~cm*#9-nOHD3CqE8o09Cr&x57*R~eFXn^NF)p>aU;&RiDxK-ckeK#RZY"
    "YD9#i`9o;SKeX%=_y~CYYM2YBh4-<(hd<HV-J^6;H>OW9$`Vl*!LvBgUa*`x$S~U(9qu1K&p&ye>G#wr^y8oU-;rS$z0cuIhtU`M"
    "G+0m}HFRaYXd3XODXntnu$<!9!(ZylvZ}xX>5TrDKC9O|U+I5CHuZ>Rzt*yH@{K-)UV8kkuGi=Ecd%Zmv~&`DMe-IKKCdMQ;t{@}"
    "t6-yR@w<bFRkG=O9neT%BG|8bD>{uzVb8fFn48HL^(8$hLDo5bfG6+Zmcf#zx^;;D#TRPClZ9y0k9uE%#Cx~ImeCe>AQiy7$lj?-"
    "EHWL8QCmO*!x}<`(W&qrm-Tv#=m7dj_aq0l?5RxZpru|zO|*miA0SvG`dJs#dgqQv7SQIu`U+hKAN7l_X33*;MO$?h-j#f-hDs$T"
    "U-^#j`ko*0Q}{qM>UW@Io=X(&5^e~@I>C}JUd~(;!zYa8)oQgmMG5{iw5A>-6!YW$5qSQ7UKVVinzg^xxd@9}2`fGTJ9!#9A!io1"
    "swupQMzX}ECnOpVv-=I^yS)~`LEkt2HgGiS2fn8g@kH4_vd_CYj6#l61HW556Fi{Q`Hi0o|KFQF;WI#*ZVtGrzX7AsFTsIke;3O^"
    "E7HMU8~TlW$!jQ)&F4G<*l`uO(B3PMob>b!TF^@^4tpj0H#bsaU-;w=)WkQ`)UTxN;2FvMIeg_<ZidgU<>r2jQ}`Ocm|OV0y)9s#"
    "E&b2IfG+^G2a%4%fNYWhF%jP2DWJm|{A~)UpWs%0A(+q;(Gohx`yx@E%*lRhKcH*<<0Lp=jyB6K(cVDD->Lgy18w|mj;tfM^&_fv"
    "!jC|@hCtT0z>#`^%btfl=0pAsfNOQo^4atQM_{j8gvt0>e2&`rQVD7-Hv}t|6R@eitTNuCeycupq=MNX%8yN=c6<U%vPM?`4chxp"
    "DXZp$EB=kZZl0txe-u55_(Y=Si6pg3D%3M{s~hFA*cP{gza!xhFd3!fM3|g28|P$2t!fDFSO9D3=x+xb=;V)s?)K$2@c(<<&%rdV"
    "^W_{0bO865knwj?*ZZA)$tPGGZLMO^yDt79Fr=>jGV10_=F&Di-H~(TH~8tk;PXUv5)5Q15Av!Y-&%^ft8^PVV-4iV@XwO$8-7+D"
    "q+QW+y3x<{$50kpbA3!Qi$=M-pY6A&9{$78E%-^0ViVs4dHp+jv!4%ZJD}D(y`e#0g=gXh$SHGJVkM%uuXq>r^fO5+7~SHR@~x2S"
    "Okj2e-{$||_VO1Y5;OEi$WTri7C`nFU^(?@@p`-?g(drAZ~u1x-DnYg5bfi?q86!kU_jY4o+4h)usWUWW!%p%L?tputO!)7#fU_x"
    "ub<<~{@x}mxm2gpZLxm-e9pz!t}vgHoGLq}@~FT6EHJq_`0N{CH+{WI@T@tAFRQ?GN6-LYGGyH0ZwC9Uz_?Y=-`z~U6Hnd<?-{P<"
    "MIPaNe0Pj5tAYNv^jrTfzlgHbP9EepcGf#dU}8rxYF)rr^L!UkO(w5W5p|7|r}F(MUx!f}><{txaDTN5(bP=7HQHIY2KreMMqP=J"
    "(kzml;yrmE5A{1C_Fo*|OvC(Arw#Brmt+s3oEYn(-t;cup1->V{w~PBv9ldK+~MJVp<e`PFH$4?h#Tk5U_@!a$7wG7AI7E`B-BaC"
    "DX3=LT8;ESj*bErNS>E0jN{h{12Lk-yq_P$IFYKQ<4!Mdfb%@sFZSPJsWK!n;Zn$Sj4wO7Bfze<u4KWA;?uTnL3rv-=JPg!jV<M$"
    "F=~tmY!fh9as|b?U;J)=tlt_MG|rd2)fPy2EX>O%HD>1Xcs~nzb^)G!3QvLUF5!EidnJA&n&1nEzZh$XF&~fUW+JfXW5hA{`kQz+"
    "mmpp)^&5w~_a6mbeG^Xsq8_HT;q2EUHOWs3&(2o^3#*{ZN7Q7$+W8$%@u&K-W4Ikn^XCHh<s|J%XSzSb&!#%W>DhS3V7gBW$6SZ^"
    "-{()`9J<-L->;8F!;Hk)^Z-7aiRZr)Sp^Tc1AT1_4VuEood^B)p5*73liad)HUK)W;df7kdf6*3)kz-mWoN65!o&V7Jg>~pp;`VT"
    "{@F0IT_-i$p98Fr>Ni!0?8d-b_Cd7f!nbxndmR59K4}9_){~b;qCmgxh~!Vu+ul#!DjE~+YRe=K=rGrx=eNQ=>GV<bQNM!AeaVf?"
    "h@~nZ^XUI%(5mM7u-#PJ4t#qWcP>;L-EPiSM=~{3`gKkZe$3CH7u0iVzbdAk&RY7Nf0Xt`7Wge`dQ3Qd3a6@t{z8(y*u{K6&4xuK"
    "s#^ZgUF6RLCwbhrVZDsSKpx;d{KpbMBdpeTp5^~Ou?k?r6aG(;C*e^V(gd#tQtiv*J-H^Lc5|ZoO+s(<{S|Mizs!HiU+yOZ-^cP?"
    "c&shZ_^xWT+nj#ypQ4=!bAY~;V3{lYxh$(vJrU(c;a}I&2Ka><$oLWu)EA?@>A~oud>KDq!Bd_F4n70k4qbsy_2?OYx^tLT`f^er"
    "gRYCzfJbDh<BqJMKI==~nik;30};WGKor{=@%kA2eZhT{SNW^`H9+mAkYyEqvjO;gi<gISovCDguQ0~2#MbHuw;p=4QtgV33s)T*"
    "fGt<~m%@Fvn|Q7N2VbI&Kl*Z(aGfvb<t9O!wz149Kj-%Vw=09U`-GL7M`vlhFDKTe{={i-JN!mhS`udemU<d<VV%2qK0ML$eiw|x"
    "WpxHVVRN`boTv&C>LO!tU!$-l$0fA5gW4ai`gU=ffXi<1H~NF|Y{~p5d*fboF9A=hcoY0lr)U@2>`&%ry%+pvy+g370x-Yxc={mv"
    "lP`Jv=djEfZ)ce)yGgx>dtUNi1`cE(?l{8o?*)!P62gH`5+ZU$NfISgA|lGBHuNX;3ho(&C#U0z_F?UTEq(<oRnGIb;4@A&-tj7M"
    "U<Hf!s^g(_HQcXxpLSI*{v1BHqk7HH(69R=pb1G_?So%<)wI=@=gV4X9m}4xZT?l-?w<i(?(pmB4c~<4V`RrsHtqD^^i%P^E&Li!"
    "ioS&wmC~2G2vXh!Z#k0d`8?u)4(>LVy!`E)Rc=1*2KyTz%oV<8kN;<%!)!AOSiIdy3wzta?dXlfPnlE$mX(T8Ivc;q*`T&M-JCfr"
    "IfggToBS9g(vtq+zU^-V58MmgJD~pJU*dhh<1CW1xChi}ZU@aR;n!d>6TAvo*g`yIzkk3_2REDpUUmV!*y_FRB-1;7Pd?};axaxm"
    "Z+Z>*jLf*Yb0Nh;{s?%9!~T2pu78-W1sjkY4Quh+RF)N*O!}+e5S;FaFSRmO$=MsQku-RaqyBq-9whyfm&wQcOs@5%?p%(laE{~i"
    "L(uc7ZWX_UF*@Nt7)1mJ-`ykjJ}_z-G&(W*H+=UN%d8~xG3d&7U~C^?l*_|?s{6qM{tj<62BVrqe~-xe<2TTex42z6r`C%<^#6g;"
    "{K%IR9B0Bgz&X(z&Qr<su|J+B@Gy*Ils`f1o6|{1a6EqA<5uEM=ISuRjAZ)E4RZvgzy=<ret5=Z*~<m}odPzV!$0z;ew{D8HiI@g"
    "^<Z{yVPrq^Wz8~2a)yP~1ZU$38zB?P7%a~_gL~`g6uj9o`ltUn#_ahp*Lga9;ZIc_o%Vl5MBR|?<#A+L^4)ggMnL+`d=!`<n-;!="
    "Y_8B5-^1^j|K(2#&mNrhB@;$6edVvjyBA}0|BZLdqOX0aCwLG(X$_*`Zq70K(EY|=fKLXZmo980E&M)(Uxx>j{EjE^)3<n9y}vgm"
    "`yiR$<2*h@F921N!G$jHIbW=^GarU*Pmt6*0FNeFzmy$g-yuSgHN=Hr54X9J2l9RO4IhUsGe)ZyPvi6c1<36vyl5T0$9L(GhyXiq"
    "H>WG&%`tQ?Jh3hN11>@i-vjR&(kSnuf613RuX1i|s0!!@c#IP?%DqWNd69FOeuOVe#?wyoWxp|Pbbs=fqD?jYA783B?32onu-Bz-"
    "SCzsw{4+*=p45s0Lv2OvRW6Vt0sLC_9SsO`49mXiE^0WR4EF&`uAKkE#)hg5^b4%L7HHQL*G`9jmK~1WR0HVW71;h&pG+5w`g-RA"
    "-svJLt91~;&}eQZnTm`uvgRqX7>;qx)8v`%c<KbaIbx1MGowZ_&v)VklLCKon=5MxPok|2VAor{LU@Ikk;pr4v`GdgcBBsK3yh0o"
    "TPmR^*f-ZJV=|y2``DUFU`SvR&1BvSt!iMR{2P2FnN(_|M^Ho4nd{)y8kxps3pX(p)YNnX-|Gb*x1Cn$rf790Nq#ktnwjP%lb6sn"
    "rjj1w7N(_XL#<4*k)8a@FlryD)_6u0wE0@o#`K6CqZgg-&LElw`<+N_4eZDivt<934BJxUw4LdxQq43z<mN(3bG;|26n$vylselW"
    "S6MNd1)tX5q#3DTHieU9?9Hz^B{w)J;2p=p)!b3;eC~*6%MK>VgZ!U_G4L<4Gv@>lNmesDnLITHGD=}N%aI5joJ|{?fw0W$(C2Ka"
    "+7wnxmA#pl@Rb(Y&w{Yp^%}&{8=PM)MYQr@n8#OUKV|}L+tJ?GIX{J;hUN_i>pDw$=;K6^%x5{!=|k>&(05r$lR9>%NVNXfT+B6S"
    "Uqd>LuWOu5(7CSA=Al5~Ghoc)!Z%F}Gi4d>1Rrvo<g}!r+)yi9K@v55y&2A(jbw;e9(@A6?gBlm4QuWG;-8={W;V3!0wh`LoWRqr"
    "N949pO=ig$H-ef#4w7qOJ0wvkb=-hXr{WXvrcP=b+ADjv>YRqa`Y1-X3P_vD&5evwE~F+kyOQy{DbT;J(C0Pa<8r1VO5M!o@j=uU"
    "EaqcKaz77-r0U(i>IU;87*V<ruir8BvA<S+orIpejhO7PBP&kbs438P5_;Xt$uKvX0Cw|}H;6LLe9kgm!E(!h&E1XcUM_&g?#q(X"
    "$&Fl~#vFrwi~>73!`Y@4(5@4>RXVQgVJ5_GGBy(9FZpJ3l%%f9P<q`NhHC{kUqUoA2{LNtj0YM#0I!z~|7{tp3?BRjaHGAz&r;{A"
    "zBa;$@4ALnGYaAF$H7{AngY7Tlwve)HSImAH9ZU?f15$vg`NetqL6yQu1|ZjFq#44$znbTwCrt`@DkwqS!$^QS9VOu?f|L8kjvZ1"
    "Lv&aGc}QiyQb#gX%L;uA5?uy88_N<qFGj2<b-&YKH8;`wh$GJM>#)z2kY?+M<V<6(b-MHI=0zu+_CnrI()0QTlGWhR7zN1*ehHp6"
    "nLKF0e(qxew<jls`{OK+#FJK$>}uE>=BF!lE-N`_*H!kPqh)<fLu&7hgBGttk9&kWoKJhqy^LgT?hHQ_xP|EPGO)-bwDc@`B0G}u"
    "@wQWt-*NPD8}L{9Pzzr7eq7p~jCM{1ZdA(Z;jcT=fpPuJAn@E=GXN+Pp&DrW@@OWt#S@RRWYUszef^E>{&+Rgf^T+C(EzjFxx?IP"
    "2AXO-V+wE7zcux+v%3s@rO7iV;p-oxdX~EJOWi?~4;&mwgMn{D%uqAT6kz;@n{8ZZ3c;a@%whVyH^Srsj~Y88O(|MA$~+azaz>l)"
    "yjp$(@6DD<NoFf#RcuH-p~m3fRJtaz6Z(0#sYU#J3N1?ItI)k;YOFaYr+mC|M(X;GH}?RiON?ZGt&7Zw$h`LiGtvBjHg-_=no={#"
    "jHAislY~5)Vm^pW#a&xynvuHOWk7^FjFeQ|ZQ-TSbTh-;XXfZ^=hpa1$}{(yxsZ7ppF`Udaqac+Q<?k;KVW8>2Tcch$YeWNKtS0O"
    "Xya|&EJ*!fv(qUvvrK{NuO2b8O<$gauenCfiB-UI=b1;%8?+hEY)|FD@AXavBsbq&myku*c^%;QC-CELr74Tdh_u1m`m<Ff(FTYp"
    "A2Ss!tJ&GkH{iYVojN)KPqR`jb>EKu&PaW{h(d(#rqWckz{r`$4<PY{#!+pA+4ASE)OVUh{hdXooE|qz-B%;yp=}K~mlm5Rq5E%8"
    "6E6ooq%1rWu`8ZMON{J;O$_s?KVc-#XFdAxBzp68RI)cpHS5kHcRd+-3%IwzSqhmn0Lx3mvz8fY(^IB1EjO0afj{-o2+4bA5o0a@"
    "=i3!#Uap~hMCMZSqMxdVe_YQmd4h2z=)LS}%HZE)46E@rQY*|ldfIG;7m><&`SiAW2A`zxD6oZLl<L;-T6p<2)SFhC8h*!<*kuJQ"
    "^I0Rg9wnExRD$TGy3#5mGaReYmo=uAtIS$hWe$)@>P7s)c>G861Ftj3={Z~>`6&z{pH?)&U2n$F4Uz=}tZb`W2y~x<h@udPwU9PB"
    "&&x79-m@0b&;~OoA%}ayzh&WyjplJTO|rF{mg;-nY+eA;u7Q3vjuhf)FGP#@qqsrz{3mln&io-}iSsY?JiQ1$(uqgFerMrLC+QO8"
    "xLGo?Q+J10YV4!|1xmvl(`yigZVOLv3WokFx9vcg1$c`1*;IE8dS8nt9~VCYDM{|SUOXC}ba7ZG_c&Oh<YXNa?$jCrdC6IUh4_Ax"
    "Q%K*l<h8#7xo?xX1bPX!F4^G^;i;$a_hmB^NGExBPthwT72j_Gdl*4^DixpPsaJt5MTl0K@M~t1vk7fq9_FHHh}N%EufyxgYLf}i"
    "6&|E&|9~pMcR8xsoIqqN)h(w26}Osp(Bz(o*i(3$*>1}4*&JwxoFP9zcSZNOxe3*NGv4j5ch+G<t7(UM!|XI~f}iEnzrZ7=VYHfo"
    "yGHo~^k)Ri*`l{hJ-kaBFp*ujE-}^=F~b|-jNd^-m#x588_{mF$27w8s_6vFzTiKb^;Bc3sE^kZp6zW|;ZwZV{KafYD8?HyAr*&<"
    "V8Q#$a*Wh|a{yz09Icf+O%at5)_y5N+hy(G30@hGc+=?}GoAk8w^WDm+k?=_ByNRXry%}XsZ${H$!JG^9_g%(Ci5Y427EIyJTcaQ"
    "51V(*9Pp0@;rwzh&fyqz|F7n7M0V&kcE+GThfTiYC0JN;xii&WOGk{MqtK0&s)Z-Mxfd5u1x=^-%oN@SZ<XiB_~gcFqI2*>S+PE5"
    "=25M25ouJ0m6%qm<3{!o*FZPQyd{WsPMG)2AuzH!=<qM#&VMs?PEXi5<V`!#`gD^-jbTka`8!B*dGrGyL=7S~VF#(Ocf}W@e>dx*"
    "Y4o9K%2!Bs<d36&n67GQc!Ia9nhI|>fCkfFRU+Q{n#u;R`zZXq)bjZl_$KF*GiB$FdJeICQdq<DI6UzuCWlVKTYPHj3@{#EGz&eE"
    "6BJc(L7)n>Dh2vI810w}Mio(cxatwELHs%h5%nZk`X{Cdv@Z|8|ID0&%)SI~U#(ZFfk2+#cvdpl#;#~?Sf#ZNdR#}1-3&0&VRFWv"
    "PMLq2-Q0xU_Zq=}@8(a;=ZFgShOv|mYmI#YpEo}?2wd;9`4Sql7(Ad0EDknHXE0uEX(i88!{}e&MuVXrWg+jH3fboJIetHS)<mIs"
    "o%t)1NdGpM>1)_pBA)&YkZcug32RoKV5w-9%D+`h!AQR~MNTs9kI!`LjpXt;2MgE+v>D3-<XnJr)@*f3_<MDUWzP9KaM|-lnAB6M"
    "Hq5&Gy-p;HQ8`EF+-Y3o)Zi^y>N;~Ko(UhcK0GmTk}epjcJaMw!so-aqKoDxn&}onLYIuJw#cl)O!tuFkwu&(_0UI#b;KG{4>yz6"
    "`9GSLblEI}{rrSTW~J)SNBKYIDb<L&0j-jNU)@M@XpZ0=G}QYef5k0TA&}x{^I!8Z^#I#ht$qQkX&!Rdck~sY${>2yTMPMS@>N6j"
    "&-8@KW42cyR~VJeCdazgvnhy6-T+4&ND-T=qILmrIl-23%t}_gm*{|61DRIyj&N3O5V+e8XD`M>YS6}^Pc7i}WPj}m^ygKM+gg?k"
    "r`j$`C=bt(G$*N~ogY0B^Q~ljGS=EG3TzKI(QZdC@6%_ffi30VSYyj!Cx?NFPpK+OLJLRnT?yAGWQRLyli*)cRXNbCp>1R*(p+k6"
    "o7igbrn$m}(OSu`bzW?Po1vF$AnU`_+<vLAu?<Oc3oE@i4rbBPR*~%gOQTjc8T~DHB>QM<d#!C_+uEOHRo-@`cJ?xTr&4Wuy9)6_"
    "H5>SD*(p+lv6Q?-9wLht7{Tt&XTX}_c>6ArjAo0}A-6rotu?3F1AgF^03%Oxfz!cuw29owc2zgfb@mq6Vo&I?q3dm_Co8){(c;dw"
    "BWy$%dKWt^p{u>@?t$0;KC;W{W^b@3aMdoS361k#1UEyg>}vHSWb+MY*a1L^Oe%~uCfRQ&E0i}v${VQK$>dWQJH)D#X|rrCdLZYF"
    "Q>idAm|x}Y)<Xo8ZF|^u@U%}Q++_2Cu{YaG+|zD_hE1d*&UX6pE%sKsn0|5}W3AJ|^UXOt49~yK_Og}K+a96YZ9d-I&y##|LsfU4"
    ";W*sR$%Ac-;68RQtm__c72=+~@VB?qCfXD&=Ds$^9zaZUiKS|BUs$^Eh!jY>kuE`e+#6#q=c^30SEW2TTmv|Yk?61bS;Uqq*Iuu3"
    "fl5vJLBvAMoaIVRl;1Dh(neHo@Ph%i1GV+@RD0-XI*{o+XN7t8<aFR+f25Nii@>+;PWS;5yTjgT2ikFtWbZ7dVa{*ulaafili%<l"
    "yFpz`rx3yPq@NNdBT7)}2j1f5*+&q)mc^2|DwYoooP#^F9jVS!0xvZf{<Z@bBR1&>UNH)CFQ&nEh<)8jhyRkf_n~$LS0T<U2v3u("
    "_N!@_odNAij}_SVh!gfn<{xm#DsbxAc*->D4*Y(I)43_w>0bUZVY(w(9tKfARjxk3sH}zW5c#JesvB-ofnriyB%KSPA$KD3RjLnS"
    "{pZ~2z>Zw-p)X`VI{oa<f)xOD)Os$mhk)1`5^4{OZ-=<B$d0EJXM}wckzJU17FhoSWZVOBXdJ!V1TC%vijTB6dZX-8-k?X@vk6jN"
    "`+zF8Ej&L~2CJ00n!YUaja@0?)=G7Adj?VDXvDixPv%>?+sY0ea3rAJSer>=p(i8b;vP6>BJg>f1=e$Sz7Xd1+~@8G`owv>mFz<0"
    "bfb5VolO(HOfIoG{0zonDL3)zB{LqMj0~p<_D)3dHDMm1Wi-Q)>=TQjO;4$n>IB}}QdROsNM#3f^I7i;Y7Flj0J(Nbr5#{mdm4pa"
    "oZ?jQ-+OEe=x9%%W<OvmBH_rx-V;jlSxzK5$59R*`jk3}|4E&U2tEy^k7Pd4lM`G|My^j77S@#9&d<Vw9)(RlMpsC3Czk@p+u_Oq"
    "(4i*OM<KQXS|!4Q2htC)h^{myq10<ZQt9+(8cFr>du<8)_e6~HEFko3;9CvFSnADnrS<TCuPKKMW0i6a68e{kD0&jcrHe{|7Fo5+"
    "=?I1^+MLOYR0(1isZLW0%^3sMX5op8*oEcRhS?qlg**GU!fQ(A_ElgKd*QpsL>5aH7x?=^>aU8S8>v9U6xeAlNv@wqV7bklU9j@="
    "oDZhmBdm*?gfT0@DAnL8+0H1mAt_qtNPfU2JQt%ZT3-MTE2reEsRQgqsYzBc)JX2iA}g~^O}td-=w4__Gp9?KxzpgzL^T^aJ=ty`"
    "$&bAdao0)}<;ivvZ1VTIlBeLiWXOH0l^kKyY(H2IVuxrPQvF_qXI!YGH<+f|K57cLRx^N__u<+j(fgrUB_vhMCeZ_S9Q<8(XRG7+"
    "i98Qukrl2Y&jttYOfPsdtz=WV0$=~2?IcwZ5y4!bhirYAzv4Z5*k)i%dwXT*$t-xCj*>qC@#PPEhE6+=;7x;J{Sh^guj(u{+s?64"
    "*(Zr2UNc;E1t`6Vq&LYV=hd(9GkhePfgY?0PwDhin`j#MQR7Iie3cXN+}qLeGqlxdEA_9`ENdVI8PhA=2~YXjl@*D4aQoigJ?acv"
    "Gt#+7&9$;;E1T~1j`1Pr_B{KjEw_^0dob+;CQIg#3OnCcTIM8-R30MHfv~I&(BPerd^J60Kd0Y8f}NcAqYLap+Za({8ZEN>dA)N5"
    "dY|ufQjf!TEVfIm%$*rnT_vn5m%7=p`~>742~VOuX`h2c<{;i(3Xj|$vYLwCZlfXYG9d3UM1W7h<84)q^h>a@@d>N&j?yr**7NZ%"
    "Xt|BRGLrGr@9k}_WXa8tQxnb#`?QTgKRX~U7)a09WLjyTweQMFP&>y3^Os7Mc-sn=lcF1Gs@oZH)Q`N{uCdeUZ(bFc(ow`=X}BiI"
    "8AwvIPFA7TT8UKuVE<^>*)8r(elqaScay=Wp0n=(RUv_dX3lzhhM%{mNOBoY0>74>o`w>ELDMm+FH^a4W8?fBb&h16NMfN4cB37E"
    ">tyB1&~_RDR5}~qWar9x2p;K8#aksy!gH{R7?5(at>A58&Db6Ef=vTgTJN;xKiPToqTL2>SPLCHPA}P!u*x-H#RGvxUFmIjjaq6("
    "PP8Zfm%6<X5*AoM1!0!F-N5Y4(BIx+l`KK_blS%+L!(~7xUNIn`k@V5Y*LshNHPt+YG1Rvc`2C3>vk93wT`Nx6L-gDKj;N$rTlG7"
    "QU&EMIj@fhbO7y(OryKF0^jGdRE7S`-D)jaT;GJY!5aL8?cgMacYwoH16_KOtn)5|Odj^Sp|x+=QPj@sfXF&kF|4kev(w7FeJ=%c"
    "$M4^?-JB2Ix2)u$ALUuZ7cy%$kJfp+Ft&T#-QZyPK%fS^$Nt&&_G)aRdfPtk);W8voZ9`1&83~O7VtQEsv1^z1#dV5YujffuU-l5"
    "mwTY!4@O(-5#gTIEwJE`PH*V#TD12&63?|dx&Zcdo_9JWkk)Q1xmJ36kGoUpEJ>xd16H2;rq@N)(L45_mHT9;qudn@&z^L1qzcd~"
    "stDIc20}ZgA_BeFYpo91Vni~sKWrcnu{SMOi|MeHxbGD;MM)*-W5DTm@yTE95scnZ`<^`pPF-ui;o}&e1F-0&d;<M^A8|qk{S7@j"
    "5w22vV2|<NZ4Q3>p_S^|lD~Z@e8W79+dr(-$coZOwhg!8kFA4$W&Lj}-tO=}qEYmIS+qBQ0x!z+I+sPHl5H}bw4d5roCZ`Cm8ylp"
    "rmlt8tbo+&z$(@w>iW!9@lyBM_<W$l5yV!fpauW5MI`#TiY}`-Z}hUApP?U%p-WMce##D_8*ue8>yp%fIO$0K)LJm3kE~?%o<|qK"
    "ahh>0+HzTKLR+KZ4#!$90qaWP2I2Zpwo?U7yq4xehrf;%;Yva5&+TcJa~xB6ar_H=+V13f{t{7*<7a`XHOJ_D0lj-fFx_qrcm1vQ"
    "vs9K+;K%ZJrTh;MoQ`Pu3p}Me7)Ta;=Of$;-YzS=st0c-(f)rSig|-&1*$n+rL$H}n||dk01A9%{|!XmjK5#w|8MMiYUxV`n{Lhp"
    "It9+r92V18Jw`>&0$9>4`W6`6i>vUvJi&2rj%2F0gXkQ%?uQtOlZcZBBR2WYe(Cn&^I+(*j$Z3DrcLG~WIF(@iO~gks1zRT{x{Z}"
    "CUbjl6R(Xn<?ro9AYumOZNPqOz<|1hwZ@ftgfH19;%k(6c3Evnhpoox2m7O~WH}{r*=peH0H9$vCj)Jp0z@lvc0)5dg&w^CjCTlF"
    "(_(1(Rk~=Uri%3cFnT@^Eo?|~F7C0gp6OIb=M4R1Wqze`m^WBfwLXMjIiTd!Sq{&LMAQ*TdNz6_ISZ6Z4_CC})PRQ2r~DuLv(2M2"
    "uoPJvdMI`RdeH+cDTesrIz%%61y3&H%jytVg`t1*jz~5AVz1c4(95ng1Ag(U-QmDvpwG;bAG;OWae*kfiWb)6(|T$KmUxusFbBsm"
    "?p^6!k{a16kc!et>;$q0OlGbm=Z0|iM|lEEHHo>rkDF0R!q1YE8{=2xNaQ?_Ts$WoKS6g$PT#Cno*zYIz8zX!jnNtamgxo1ekT%~"
    "MJy)!M;z`8UH=3uFB$#22+mRh?dXZ$HpSOkd^Q>X?uDF7STb|<<!JD@+ni4GRZ0jR;m7b)sVou;_Q}aKN7hN_a6Hg~tc~U-lq<>I"
    "S^$l)5kGi?W%aoJe=-~#1B)$(rnTnI80|OE!>jbUTfru1?<M1&DZqZl_*{j(9Y_0Ykcgh=$y%|J{kYAXn&>Jm@_#>i5PDEgJ0OWf"
    "4qVy4A*V@}N4w(gcf<M)e*pu26i7G=Z!LgkO@MXDzB{lq5<V}x+-f14zTBDLfTS6icG2kx4ynNTE79@-$YeJBrMy26IxZX{2u!$x"
    "Au(tW{3f^{S^a_%uBKFeKsOAU@^`8PjKNb<^`cSG7*|i1tVpreoF8ivER9KR_)dsH^5K^+q2<#d=Ow()jY}N}M7N*0x!~~^ou+}*"
    "=dK3BlGBpIFwR?@CE#>>+$3P@?NkT6x&XO03)17I)I6vsiz}}Qu5nr`igZ-PBw4MOV6<;@TLT9tBKqsguYm8i2zpbZYKz`iLhGdV"
    "hh#piLS))9I7ap1>GvU!b*tc8++WYh!C=@^AN7E3jqjo)KedI|lDX|`gJfzGv<=2lR4bJdc+?KxpGQ3DBIfGjcj9i88c3asWNOW_"
    "^3XnT!#Vg2l9jzIcsa?(bPQ}q_IVocss;3++l>mGt8}NAMyu3|DlNDz;iU7n>ZCfr0#a4A^Ah#*uCVMP?GWSvH%1|bngF?8l;}H%"
    "!m2vK?yd_OQ4aK?j+C20*9SXjq+1YcL!E;ms!Onw@6&SPKMNz<5bS3iJpc32d}_*FgVL}f`%xAvtLJV(6<yRnMsEl*piQZq9>{5z"
    "P4H3K7_W4G3<z4n7G8K7Vy+e;@{FN2<f+cEtVWa(Jco$o#vl_>!${n*n`Qr(oC-dN{uD}<x*!ktNTrA!h^dZ1=fK8*yGNmETb(#("
    "1smw$gr|WMvgWxPqslx)$v)X?v>mA6lyK89KVzcm%iRN+>23zkm>pz<m0!p5<8F^&GFOsh1Z))MUrhmb&!(G#n}Z1Tgic5m_3dCa"
    "kMVr8dMjOY1c9VR^esUl_};BSFTO319KKRvr$U{8{;c48;R#+vyZ5-V1FBb01?z7FZzznlt5hcmZpS?_>ZeAKgP6G<$X*U99wf=M"
    "SMKxyZfvGRuQNW$a|R(^6%@`vZyNDw@1oPd8;vNTFJ!j?>?0rCvxr11dQ(1R_-D=uo<(e#M>02%1C5s*%>8Aq53DxMc`W<BM!GpP"
    "1V6RHXlLW63mD@hMEWT~2aHAr{6`g?_T-JS*JPDsCPi!H+(>1Zov|T$*9Ifk%&BI{xc{{yJbHPwM;Ij^fyWr4c1Sg8Tv>?LFH~|G"
    "tpu{n0N+XBMv(Jlpy?Jc$BWJiAWs9dwHNop)9>}Vvq+{2Qanc);rf8gt(Sv0jz$ls;L3ghhkJK(gOeD)Z0aARfsGW=fS@7%zYH%k"
    "hjSBpL-Xzk-m_Qu&Olb7&c?6CWL-1~?M`CZN8OGl0#9UiY9<(Y37$|(1L1Y9(hM(C&MAS#&f!z^+n{ymp|j{}><D6d1HWW&_g#Tx"
    "J1J(#nN$jounVX@D2TXH|4Mc)AB<kqYr>Na*8>F?&@b@$OA-!KH(WDBrSNc)y0RxY54Kr|SVLAO%EP>Ab+Ru`>hpwaQNj;vI6vqK"
    "i4G3-@;4aUB#d`94GFr?9g!ANfth!}`tMPh;a%;}Zpro7gle69*yC2G6hBW3x$DCTg|MY&7_n}?2R||t(kypm4}#PW&vPDkV;G_F"
    "UhnYD9cUQ*{a8K$za~2*hXIGrv*e{L2!;n)u**UqPEk+{Kfa2_ISp}@<nD^VdgR3MqJ$g0*WGBihA2@;a(I#>m%jo+G&GF1J_`Q_"
    "q(?lQMz1?#U_%EIm}a6a2R((@FA>rx4|7}er14V6A!trA*E3W}&SbHg&G=a=!*x*-2du&~3(%vk7@0V~?yN#Y#2EGBXaVm`kTq4Q"
    "k1~auU=&}XZ-uMl%Cu-T5$tg(_+OmQAVMxzq>6bYJV_=Er%^#$*)7SJq0=)V-)Ep@NqmH)epowT`4?0hdSE$0CTvCa#GHl)inzz2"
    "S;NC>^5x+!*F_1!#ekU5ntN296NA<CWLZ}pD^<79qu!8V3a)DenVrW~BDZmlNK<wL$)1v8;HiSwoE4tRj{{Aopbx!)ggGpXW0_<%"
    "<?oeMGN%aUp!#{OXsMe<ql2YxFI61ujLRu%S(h=Aj}VsJ8Fnit3ft1o_%s>=1pbXT6tc-gBqmurrU^fQ)hu--4n9NAL;oZml^VhI"
    "==t?38+SP1brzE7h|lG_M|rh#cd!ZXSsoo5l(E!5Tt*(E+y^0(p{j=0gvd2SU2E$S>Jp>^c{;TJ?XZ67V=Q?y#s%Y{qY>fhkVi6N"
    "n|p#;sw9y8)yXsgK6hde<9mZr@T*Diu8SPmuNLRYc%RJPObMn2a}YVz(=6vZpfK}pUcnC7RvpIcd5qVzAj%_nG0;l(5cu$*va>h|"
    "sMSSH4`g0@A4`tRGWeh?+|=EHd)lKlrT?>vHBWN(LqeT+Mj)rRWF1O!v@Z>7eKi70xDVEQe^5aW1k<1u<D6;S1Z;k0FbW8|Hk{A+"
    "geAk{dPlN^w<DWS0S#M14+akfhw-F`gFS97<o~D0&vJG-$VSxLi#It_>9RYCevBTaS-~UFRarls9i+(l1zH+g9<AU>w2WqkPd)?d"
    "$-*-(0KW_ABS+S%>m`$M(2wQ@^U!k1U}pKzpbS@)k$g{F4%XnPih$Hsbp{qF+5i9d&lD!GmtX%ZkN)qcpYs2`0Gj{*{;34(kv|jv"
    "?<Xzk6vv@c|NEx|<NyEvX9YBAejwjPsT-K0R32gOikSZ@bhm&`0%M7~sw?z=02yUMOa"
)

_VOCAB_CACHE: Optional[Tuple[Tuple[str, ...], ...]] = None
_IDX_CACHE: Optional[array.array] = None

_SEP_RE = re.compile(r"[\s_\-·•・/\\()（）\[\]【】:,：，.。]+")
_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _ensure_loaded() -> Tuple[Tuple[Tuple[str, ...], ...], array.array]:
    global _VOCAB_CACHE, _IDX_CACHE
    if _VOCAB_CACHE is None or _IDX_CACHE is None:
        raw_vocab = zlib.decompress(base64.b85decode(_VOCAB_B85)).decode("ascii").split("\n")
        _VOCAB_CACHE = tuple(tuple(s.split(",")) if s else () for s in raw_vocab)
        arr = array.array("H")
        arr.frombytes(zlib.decompress(base64.b85decode(_IDX_B85)))
        _IDX_CACHE = arr
    return _VOCAB_CACHE, _IDX_CACHE


def has_cjk(text: str) -> bool:
    """Return True if text contains any CJK ideograph."""
    return bool(text and _CJK_CHAR_RE.search(text))


def char_pinyins(ch: str) -> Tuple[str, ...]:
    """Return ordered lowercase ASCII Pinyin readings for a single CJK character."""
    if not ch:
        return ()
    cp = ord(ch)
    if _START_CP <= cp <= _END_CP:
        vocab, idx = _ensure_loaded()
        vid = idx[cp - _START_CP]
        return vocab[vid] if vid else ()
    return ()


def _tokenize_mixed_segment(seg: str) -> List[Tuple[str, Tuple[str, ...]]]:
    """Split a separator-free segment into (kind, options) tokens.

    kind == "cjk": each character yields its tuple of lowercase pinyin readings.
    kind == "ascii": contiguous ASCII alphanumeric run preserving original casing as metadata.
    """
    out: List[Tuple[str, Tuple[str, ...]]] = []
    i = 0
    n = len(seg)
    while i < n:
        ch = seg[i]
        if _START_CP <= ord(ch) <= _END_CP:
            pys = char_pinyins(ch)
            if pys:
                out.append(("cjk", pys))
            i += 1
        elif ch.isascii() and ch.isalnum():
            j = i + 1
            while j < n and seg[j].isascii() and seg[j].isalnum():
                j += 1
            out.append(("ascii", (seg[i:j],)))
            i = j
        else:
            i += 1
    return out


def _expand_token_combos(tokens: List[Tuple[str, Tuple[str, ...]]], max_combos: int = 36) -> List[List[Tuple[str, str]]]:
    """Expand multi-reading polyphones prioritizing primary readings first, bounded by max_combos."""
    if not tokens:
        return []
    # Always start with primary (index 0) reading for every token
    primary = [(kind, opts[0]) for kind, opts in tokens]
    results: List[List[Tuple[str, str]]] = [primary]
    seen = {tuple(v.lower() for _, v in primary)}

    # Stage 1: single-character polyphone substitutions (most realistic & clean)
    for pos, (kind, opts) in enumerate(tokens):
        if len(opts) <= 1:
            continue
        for alt in opts[1:]:
            if len(results) >= max_combos:
                return results
            cand = list(primary)
            cand[pos] = (kind, alt)
            sig = tuple(v.lower() for _, v in cand)
            if sig not in seen:
                seen.add(sig)
                results.append(cand)

    # Stage 2: bounded Cartesian expansion for multi-polyphone short names (<= 6 tokens)
    if len(tokens) <= 6 and len(results) < max_combos:
        frontier: List[List[Tuple[str, str]]] = [[]]
        for kind, opts in tokens:
            next_frontier: List[List[Tuple[str, str]]] = []
            for prefix in frontier:
                for opt in opts[:2]:
                    next_frontier.append(prefix + [(kind, opt)])
                    if len(next_frontier) >= max_combos * 2:
                        break
                if len(next_frontier) >= max_combos * 2:
                    break
            frontier = next_frontier
        for cand in frontier:
            if len(results) >= max_combos:
                break
            sig = tuple(v.lower() for _, v in cand)
            if sig not in seen:
                seen.add(sig)
                results.append(cand)

    return results


def _format_part_forms(combo: List[Tuple[str, str]]) -> Tuple[str, List[str]]:
    """Build (lowercase_form, capitalized_forms) for one separator-free segment combo."""
    low_parts: List[str] = []
    pascal_parts: List[str] = []
    # Keep uppercase acronyms like EX in JueseEX, otherwise capitalize first letter
    for kind, val in combo:
        if kind == "cjk":
            low_parts.append(val.lower())
            pascal_parts.append(val.capitalize())
        else:
            low_parts.append(val.lower())
            if val.isupper() and len(val) >= 2:
                pascal_parts.append(val)
            elif any(c.isupper() for c in val[1:]) and any(c.islower() for c in val):
                # Preserve existing CamelCase / PascalCase (e.g. LinNai, ChangLi, BaiLian)
                pascal_parts.append(val[0].upper() + val[1:])
            else:
                pascal_parts.append(val.capitalize())

    lower_joined = "".join(low_parts)
    caps: List[str] = []
    # 1. Standard first-letter capitalized (e.g. "Lili", "Aimisi", "Xigelika", "Jinxi")
    if lower_joined:
        first_cap = lower_joined[0].upper() + lower_joined[1:]
        if first_cap not in caps:
            caps.append(first_cap)
    # 2. If trailing ASCII uppercase acronym exists (e.g. "角色EX" -> "JueseEX")
    if len(combo) >= 2 and combo[-1][0] == "ascii" and combo[-1][1].isupper():
        head_low = "".join(v.lower() for _, v in combo[:-1])
        tail_raw = combo[-1][1]
        if head_low:
            acr_cap = head_low[0].upper() + head_low[1:] + tail_raw
            if acr_cap not in caps:
                caps.append(acr_cap)
    # 3. Full per-syllable PascalCase (e.g. "LinNai", "BaiLian", "ChangLi", "YinLin")
    pascal_joined = "".join(pascal_parts)
    if pascal_joined and pascal_joined not in caps:
        caps.append(pascal_joined)
    # 4. Prefix+last-syllable PascalCase for 3+ syllable compound names (e.g. "守岸人" -> "ShouanRen")
    if len(combo) >= 3:
        head_low = "".join(v.lower() for _, v in combo[:-1])
        last_cap = pascal_parts[-1]
        if head_low and last_cap:
            tail_split = head_low[0].upper() + head_low[1:] + last_cap
            if tail_split not in caps:
                caps.append(tail_split)
    # 5. First-2-syllables + rest split for 4-syllable names
    if len(combo) >= 4:
        for cut in range(2, len(combo) - 1):
            left = "".join(v.lower() for _, v in combo[:cut])
            right = "".join(v.lower() for _, v in combo[cut:])
            if left and right:
                split_cap = left[0].upper() + left[1:] + right[0].upper() + right[1:]
                if split_cap not in caps:
                    caps.append(split_cap)
    return lower_joined, caps


def text_to_pinyin_variants(text: str, *, max_combinations: int = 36) -> Dict[str, List[str]]:
    """Convert Chinese/mixed query into ordered lowercase, capitalized/PascalCase, and underscore forms.

    Returns:
      {
        "lower": [...],        # e.g. ["lili"], ["jinxi"], ["shouanren"]
        "capitalized": [...],  # e.g. ["Lili", "LiLi"], ["ChangLi"], ["LinNai"]
        "syllables": [...],    # primary syllable sequence for diagnostics
      }
    """
    raw = (text or "").strip()
    if not raw or not has_cjk(raw):
        return {"lower": [], "capitalized": [], "syllables": []}

    # Split on explicit separators first so "弗洛洛·礼服" / "弗洛洛 礼服" keeps segment boundaries
    raw_segments = [s for s in _SEP_RE.split(raw) if s]
    if not raw_segments:
        return {"lower": [], "capitalized": [], "syllables": []}

    lower_out: List[str] = []
    cap_out: List[str] = []

    def _add_low(s: str) -> None:
        if s and s not in lower_out:
            lower_out.append(s)

    def _add_cap(s: str) -> None:
        if s and s not in cap_out:
            cap_out.append(s)

    # Whole compact sequence (ignoring separators)
    all_tokens: List[Tuple[str, Tuple[str, ...]]] = []
    seg_token_lists: List[List[Tuple[str, Tuple[str, ...]]]] = []
    for seg in raw_segments:
        toks = _tokenize_mixed_segment(seg)
        if toks:
            seg_token_lists.append(toks)
            all_tokens.extend(toks)

    if not all_tokens:
        return {"lower": [], "capitalized": [], "syllables": []}

    primary_sylls = [opts[0].lower() for _, opts in all_tokens]

    # Multi-segment forms first if user provided explicit separators (e.g. "弗洛洛·礼服" -> "Fuluoluo_Lifu", "fuluoluo_lifu")
    if len(seg_token_lists) >= 2:
        seg_primary_lows: List[str] = []
        seg_primary_caps: List[str] = []
        for stoks in seg_token_lists:
            combos = _expand_token_combos(stoks, max_combos=4)
            if combos:
                lw, cps = _format_part_forms(combos[0])
                seg_primary_lows.append(lw)
                seg_primary_caps.append(cps[0] if cps else lw.capitalize())
        if len(seg_primary_lows) >= 2:
            _add_low("".join(seg_primary_lows))
            _add_low("_".join(seg_primary_lows))
            _add_cap("_".join(seg_primary_caps))
            _add_cap("".join(seg_primary_caps))

    # Full sequence polyphone expansion
    combos = _expand_token_combos(all_tokens, max_combos=max_combinations)
    for combo in combos:
        lw, cps = _format_part_forms(combo)
        _add_low(lw)
        for c in cps:
            _add_cap(c)

    return {"lower": lower_out, "capitalized": cap_out, "syllables": primary_sylls}
