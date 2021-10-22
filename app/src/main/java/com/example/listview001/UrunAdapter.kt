package com.example.listview001

import android.app.Activity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import com.bumptech.glide.Glide

class UrunAdapter(private val context: Activity, private val urunler: ArrayList<Urun>)
    : ArrayAdapter<Urun>(context, R.layout.custom_list, urunler) {

    override fun getView(position: Int, view: View?, parent: ViewGroup): View {
        val inflater = context.layoutInflater
        val rowView = inflater.inflate(R.layout.custom_list, null, true)

        val titleText = rowView.findViewById(R.id.title) as TextView
        val imageView = rowView.findViewById(R.id.icon) as ImageView
        val subtitleText = rowView.findViewById(R.id.description) as TextView

        titleText.text = urunler[position].baslik
        //imageView.setImageResource(R.drawable.foodicon)

        /*
        Glide.with(context)
            .load("http://10.0.2.2:5000/static/iskender.png")
            .into(imageView)
         */
        Glide.with(context)
            .load(urunler[position].fotoUrl)
            .into(imageView)
        subtitleText.text = urunler[position].detay

        return rowView
    }
}